import warnings
from unsloth import FastVisionModel,UnslothVisionDataCollator
from transformers import TrainingArguments, TextIteratorStreamer
from unsloth_zoo.vision_utils import process_vision_info, get_padding_tokens_ids, _get_dtype
import torch
import json
from unsloth import is_bf16_supported
from trl import SFTTrainer, SFTConfig
from threading import Thread
from PIL import Image
from datasets import load_dataset


warnings.simplefilter("ignore", SyntaxWarning)


class FastVLLM:
    """
    A class for loading, training, and generating text with a FastVisionModel.
    """

    def __init__(self):
        self.chat_history = []
        self.images_history = []
        self.model = None
        self.processor = None
        self.converted_dataset = None
        self._trainer = None
        self.load_in_4bit = False
        self.load_in_8bit = False
        self.streamer = None

    def load_model(self, model_name, dtype=None, load_in_4bit=False, load_in_8bit=False, **kwargs):
        """Loads the FastVisionModel and its processor."""
        self.model, self.processor = FastVisionModel.from_pretrained(
            model_name=model_name,
            dtype=dtype,
            load_in_4bit=load_in_4bit,
            load_in_8bit=load_in_8bit,
            **kwargs
        )
        self.load_in_4bit = load_in_4bit
        self.load_in_8bit = load_in_8bit

    def load_dataset(self, dataset):
        """Loads and sets the dataset for training."""
        self.converted_dataset = dataset

    def save_model(self, model_name, save_method="merged_16bit", **kwargs):
        """Saves the model, handling different quantization methods."""
        if self.load_in_4bit or self.load_in_8bit or save_method == "16bit":
            try:
                self.model.save_pretrained_merged(model_name, self.processor, save_method=save_method, **kwargs)
            except:
                self.load_dataset(None)
                self.model.save_pretrained_merged(model_name, self.processor, save_method=save_method, **kwargs)

            if save_method == "merged_16bit":
                config = json.loads(self.model.config.to_json_string())
                for key in ["_attn_implementation_autoset", "quantization_config"]:
                    try:
                        del config[key]
                    except KeyError:
                        pass
                with open(f"{model_name}/config.json", "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
        else:
            self.model.save_pretrained(model_name)
            self.processor.save_pretrained(model_name)

    def trainer(
        self,
        max_seq_length=2048,
        learning_rate=2e-4,
        output_dir="outputs",
        callbacks=None,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        report_to="none",
        remove_unused_columns=False,
        dataset_num_proc=4,
        finetune_vision_layers=True,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        random_state=3407,
        use_rslora=False,
        loftq_config=None,
        data_callator=None,
        **kwargs
    ):
        """Configures the SFTTrainer for fine-tuning."""
        self.model = FastVisionModel.get_peft_model(
            self.model,
            finetune_vision_layers=finetune_vision_layers,
            finetune_language_layers=finetune_language_layers,
            finetune_attention_modules=finetune_attention_modules,
            finetune_mlp_modules=finetune_mlp_modules,
            r=r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            bias=bias,
            random_state=random_state,
            use_rslora=use_rslora,
            loftq_config=loftq_config,
        )

        FastVisionModel.for_training(self.model)
            
        if data_callator == None:
            data_callator = UnslothVisionDataCollator(
                self.model,
                self.processor,
            )

        self._trainer = SFTTrainer(
            model=self.model,
            tokenizer=self.processor,
            data_collator=data_callator,
            train_dataset=self.converted_dataset,
            callbacks=callbacks,
            args=SFTConfig(
                per_device_train_batch_size=per_device_train_batch_size,
                gradient_accumulation_steps=gradient_accumulation_steps,
                warmup_steps=warmup_steps,
                learning_rate=learning_rate,
                fp16=not is_bf16_supported(),
                bf16=is_bf16_supported(),
                optim=optim,
                weight_decay=weight_decay,
                lr_scheduler_type=lr_scheduler_type,
                seed=seed,
                output_dir=output_dir,
                report_to=report_to,
                remove_unused_columns=remove_unused_columns,
                dataset_text_field="",
                dataset_kwargs={"skip_prepare_dataset": True},
                dataset_num_proc=dataset_num_proc,
                max_seq_length=max_seq_length,
                **kwargs
            ),
        )
        gpu_stats = torch.cuda.get_device_properties(0)
        start_gpu_memory = round(torch.cuda.max_memory_reserved() / 1024 / 1024 / 1024, 3)
        max_memory = round(gpu_stats.total_memory / 1024 / 1024 / 1024, 3)
        print(f"GPU = {gpu_stats.name}. Max memory = {max_memory} GB.")
        print(f"{start_gpu_memory} GB of memory reserved.")

    def start_train(self):
        """Starts the training process."""
        self._trainer.train()

    def resize_image_pil(self, image, max_size=1100):
        """Resizes an image using PIL."""
        img_copy = image.copy()
        img_copy.thumbnail((max_size, max_size))
        return img_copy

    def generate(
        self,
        text="",
        images=None,
        max_new_tokens=512,
        stream=False,
        history_save=True,
        apply_chat_template=True,
        temperature=0.4,
        top_p=0.9,
        end=None,
        add_images_to_model_history=False,
        max_images_size=1000,
        **kwargs
    ):
        """Generates text based on the given input and model."""
        if end is None:
            end = [self.processor.tokenizer.eos_token]

        FastVisionModel.for_inference(self.model)
        if images is None:
            messages = {"role": "user", "content": [{"type": "text", "text": text}]}
        else:
            messages = {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}

        self.chat_history.append(messages)
        if images is not None:
            images = self.resize_image_pil(images, max_images_size)
            self.images_history.append(images)

        imagess = self.images_history
        if not add_images_to_model_history:
            chat = [
                {'role': his['role'], 'content': [k for k in his['content'] if k['type'] == 'text']}
                if his['role'] == 'user' else his for his in self.chat_history[:-1]
            ] + [self.chat_history[-1]]
            if images:
                imagess = [images]
            else:
                imagess = []

        self.streamer = TextIteratorStreamer(
            self.processor, skip_prompt=True, skip_special_tokens=True, do_sample=True, temperature=temperature, top_p=top_p
        )
        if apply_chat_template:
            input_text = self.processor.apply_chat_template(chat, add_generation_prompt=True)
            input_ids = self.processor(
                None if not imagess else imagess, input_text, add_special_tokens=False, return_tensors="pt"
            ).to(self.model.device)

        if not history_save:
            if text:
                del self.chat_history[-1]
            if images is not None:
                del self.images_history[-1]

        terminators = [self.processor.tokenizer.eos_token_id] + [
            self.processor.tokenizer.convert_tokens_to_ids(i) for i in end
        ]
        if stream:
            thread = Thread(
                target=self.model.generate,
                kwargs={
                    **input_ids,
                    "streamer": self.streamer,
                    "max_new_tokens": max_new_tokens,
                    "eos_token_id": terminators,
                    "do_sample": True,
                    "temperature": temperature,
                    "top_p": top_p,
                    **kwargs,
                },
            )
            thread.start()

            def inner():
                i = 0
                text_out = ""
                for new_text in self.streamer:
                    i += 1
                    if i != 1:
                        text_out += new_text
                        for te in new_text:
                            yield te
                if history_save:
                    self.chat_history.append({"role": "assistant", "content": [{"type": "text", "text": text_out}]})

                thread.join()

            return inner()
        else:
            outputs = self.model.generate(
                **input_ids,
                max_new_tokens=max_new_tokens,
                eos_token_id=terminators,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            )
            response = outputs[0][input_ids["input_ids"].shape[-1]:]
            text_out = self.processor.decode(response, skip_special_tokens=True)
            if history_save:
                self.chat_history.append({"role": "assistant", "content": [{"type": "text", "text": text_out}]})

            return text_out


if __name__ == "__main__":
    model = FastVLLM()
    model.load_model("Llama-3.2-11B-Vision-Instruct", load_in_4bit=True)
    dataset = load_dataset("unsloth/Radiology_mini", split="train")
    dataset = dataset.select(range(5))

    instruction = "You are an expert radiographer. Describe accurately what you see in this image."

    def convert_to_conversation(sample):
        conversation = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": sample["image"]}
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": sample["caption"]}],
            },
        ]
        return {"messages": conversation}

    converted_dataset = [convert_to_conversation(sample) for sample in dataset]

    model.load_dataset(converted_dataset)
    model.trainer(max_steps=60, logging_steps=1)

    model.start_train()
