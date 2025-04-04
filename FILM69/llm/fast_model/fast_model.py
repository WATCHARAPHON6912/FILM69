import warnings,os,shutil
from unsloth import FastModel as _FastModel
from transformers import TrainingArguments,TextIteratorStreamer
from pathlib import Path
warnings.simplefilter("ignore", SyntaxWarning)

from unsloth_zoo.vision_utils import process_vision_info,get_padding_tokens_ids,_get_dtype
import torch,json
from unsloth import is_bf16_supported
from trl import SFTTrainer, SFTConfig
from threading import Thread
from PIL import Image
from datasets import load_dataset
from unsloth import UnslothVisionDataCollator
class FastModel:
    def __init__(self) -> None:
        self.chat_history = []
        self.images_history=[]
    
    def load_model(self,model_name,dtype=None,load_in_4bit=False,load_in_8bit=False,**kwargs): 
        self.model, self.processor = _FastModel.from_pretrained(
            model_name = model_name,
            dtype = dtype,
            load_in_4bit = load_in_4bit,
            load_in_8bit=load_in_8bit,
            **kwargs
        )
        self.load_in_4bit=load_in_4bit
        self.load_in_8bit=load_in_8bit
    
    def load_dataset(self,dataset):
        self.converted_dataset=dataset
    
    def save_model(self,model_name,save_method = "merged_16bit",**kwargs):
        
        if self.load_in_4bit==True or self.load_in_8bit==True:
            try:
                self.model.save_pretrained_merged(model_name, self.processor, save_method = save_method,**kwargs)
            except:
                self.load_dataset(None)
                self.model.save_pretrained_merged(model_name, self.processor, save_method = save_method,**kwargs)
            if save_method=="merged_16bit":
                config=json.loads(self.model.config.to_json_string())
                try:del config["_attn_implementation_autoset"]
                except:...
                try:del config["quantization_config"]
                except:...
                with open(f"{model_name}/config.json", "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
                    
        else:
            self.model.save_pretrained(model_name)
            self.processor.save_pretrained(model_name)
            
    def trainer(self,
        max_seq_length=2048,
        learning_rate=2e-4,
        output_dir = "outputs",
        callbacks=None,
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        report_to = "none",
        remove_unused_columns = False,
        dataset_num_proc = 4,
        
        finetune_vision_layers     = True, # False if not finetuning vision layers
        finetune_language_layers   = True, # False if not finetuning language layers
        finetune_attention_modules = True, # False if not finetuning attention layers
        finetune_mlp_modules       = True, # False if not finetuning MLP layers
        r = 16,           # The larger, the higher the accuracy, but might overfit
        lora_alpha = 16,  # Recommended alpha == r at least
        lora_dropout = 0,
        bias = "none",
        random_state = 3407,
        use_rslora = False,  # We support rank stabilized LoRA
        loftq_config = None, # And LoftQ    
        
        train_on_responses_only = False,
        instruction_part = "<|start_header_id|>user<|end_header_id|>\n\n",
        response_part = "<|start_header_id|>assistant<|end_header_id|>\n\n",   
        **kwargs):
        "trainer(self,max_seq_length=1024,max_step=60 or num_train_epochs=3,learning_rate=2e-4,output_dir = 'outputs',callbacks=None)"
        self.model = _FastModel.get_peft_model(
            self.model,
            finetune_vision_layers     = finetune_vision_layers,
            finetune_language_layers   = finetune_language_layers,
            finetune_attention_modules = finetune_attention_modules,
            finetune_mlp_modules       = finetune_mlp_modules,

            r = r,           
            lora_alpha = lora_alpha, 
            lora_dropout = lora_dropout,
            bias = bias,
            random_state = random_state,
            use_rslora = use_rslora,  
            loftq_config = loftq_config, 
        )
        
        # _FastModel.for_training(self.model) 

        self._trainer = SFTTrainer(
            model = self.model,
            tokenizer = self.processor,
            data_collator = UnslothVisionDataCollator(
                    self.model,
                    self.processor,
                    train_on_responses_only = train_on_responses_only,
                    instruction_part = instruction_part,
                    response_part = response_part,
                ),
            # data_collator = DataCollator(self.model, self.processor), # Must use!
            train_dataset = self.converted_dataset,
            callbacks=callbacks,
            args = SFTConfig(
                per_device_train_batch_size = per_device_train_batch_size ,
                gradient_accumulation_steps = gradient_accumulation_steps,
                warmup_steps = warmup_steps,
                learning_rate = learning_rate,
                fp16 = not is_bf16_supported(),
                bf16 = is_bf16_supported(),
                optim = optim,
                weight_decay = weight_decay,
                lr_scheduler_type = lr_scheduler_type ,
                seed = seed,
                output_dir = output_dir,
                report_to = report_to,

                remove_unused_columns = remove_unused_columns,
                dataset_text_field = "",
                dataset_kwargs = {"skip_prepare_dataset": True},
                dataset_num_proc = dataset_num_proc,
                max_seq_length = max_seq_length,
                **kwargs
            ),
        )
        gpu_stats = torch.cuda.get_device_properties(0)
        start_gpu_memory = round(torch.cuda.max_memory_reserved() / 1024 / 1024 / 1024, 3)
        max_memory = round(gpu_stats.total_memory / 1024 / 1024 / 1024, 3)
        print(f"GPU = {gpu_stats.name}. Max memory = {max_memory} GB.")
        print(f"{start_gpu_memory} GB of memory reserved.")

    def start_train(self):
        self._trainer.train()
        
    def resize_image_pil(self,image, max_size=1100):
        img_copy = image.copy()
        img_copy.thumbnail((max_size, max_size))
        return img_copy

    def generate(self,
        text:str="",
        image:Image =None,
        max_new_tokens:int=512,
        stream:bool=False,
        history_save:bool=True,
        temperature=0.4,
        top_p=0.9,
        max_images_size=1000,
        **kwargs):

        _FastModel.for_inference(self.model)
        
        if image !=None:
            image=self.resize_image_pil(image,max_images_size)
            self.images_history.append(image)
        
        if image==None:messages = {"role": "user", "content": [{"type": "text", "text": text}]}
        else:
            messages = {
                "role": "user", 
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": text}
                    ]
                }
        
        self.chat_history.append(messages)
        print(self.chat_history)
        print("#"*100)
    
        self.streamer = TextIteratorStreamer(self.processor, skip_prompt=True, skip_special_tokens=True)

        # text = self.processor.apply_chat_template(
        #     self.chat_history if history_save else [messages],
        #     add_generation_prompt=True,
        # )
        # input_ids=self.processor([text], return_tensors = "pt").to("cuda")
        
        input_ids = self.processor.apply_chat_template(
            self.chat_history if history_save else [messages],
            add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt"
        ).to(self.model.device)
        
        if history_save==False:
            if text != "":del self.chat_history[-1]
        
        if stream==True:
            thread = Thread(target=self.model.generate, kwargs=
                            {
                            **input_ids,
                            "streamer": self.streamer,
                            "max_new_tokens": max_new_tokens,
                            "do_sample":True,
                            "temperature":temperature,
                            "top_p":top_p,
                            **kwargs
                                
                            })
            thread.start()
            
            def inner():
                i=0
                text_out=""
                for new_text in self.streamer:
                    i+=1
                    if i!=1:
                        text_out+=new_text
                        for te in new_text:yield  te
                if history_save:self.chat_history.append({ "role" : "assistant","content" : [{"type":"text","text": text_out}]})
                
                thread.join()
            return inner()
        else:
            outputs = self.model.generate(
                **input_ids,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            )
            
            response = outputs[0][input_ids["input_ids"].shape[-1]:]
            text_out=self.processor.decode(response, skip_special_tokens=True)
            if history_save:self.chat_history.append({ "role" : "assistant","content" : [{"type":"text","text": text_out}]})

            return text_out
        
    def export_to_GGUF(self,model_name="model",quantization_method= ["q4_k_m","q8_0","f16"],save_original_model=False,max_size_gguf="49G",build_gpu=False,save_original_gguf=False,**kwargs):
        
        _FastModel.for_inference(self.model)
        self.model.save_pretrained_gguf(model_name, self.processor, quantization_method = quantization_method,**kwargs)
        source_directory = Path(model_name)
        gguf_directory = source_directory / 'GGUF'
        max_size_gguf=max_size_gguf.upper()

        gguf_directory.mkdir(exist_ok=True)
        for file_path in source_directory.rglob('*unsloth*'):
            if file_path.is_file():
                new_file_name = file_path.name.replace('unsloth', model_name)
                new_file_path = gguf_directory / str(new_file_name).split("/")[-1]
                shutil.move(str(file_path), str(new_file_path))
                print(f'saved {new_file_path}')

        if not save_original_model:
            for item in os.listdir(model_name):
                item_path = os.path.join(model_name, item)
                if os.path.isfile(item_path):os.remove(item_path)
        
        # move folder
        folder_path = f"{model_name}/GGUF"
        files_path,files_size = self.__check_file__(folder_path)

        if max(files_size) > self._convert_to_gb(max_size_gguf):
            for i in files_path:
                new_path = os.path.join(folder_path, i.split('.')[-2])
                os.makedirs(new_path, exist_ok=True)
                shutil.move(i, os.path.join(new_path, i.split('/')[-1]))
        
        # build llama.cpp
        if os.system("./llama.cpp/llama-gguf-split") != 256:
            build_gpu_command="-DGGML_CUDA=ON"
            command=f"""
                cd llama.cpp && \
                cmake -B build {build_gpu_command if build_gpu else ''} && \
                cmake --build build --config Release && \
                cp build/bin/llama-* .
                """
            os.system(command)
        
        # split gguf
        files_path,files_size = self.__check_file__(folder_path)
        for i in range(len(files_path)):
            if files_size[i] > self._convert_to_gb(max_size_gguf):
                command=f"""./llama.cpp/llama-gguf-split --split \
                    --split-max-size {max_size_gguf}\
                    {files_path[i]} {files_path[i][:-5]}
                """
                os.system(command)
                if not save_original_gguf:
                    os.remove(files_path[i])

    def _convert_to_gb(self,size_str):
        unit_multipliers = {
            'M': 1 / 1024,
            'G': 1          
        }

        num = float(size_str[:-1])
        unit = size_str[-1]
        
        return num * unit_multipliers.get(unit, 1)

    def __check_file__(self,path):
        files_path = []
        files_size = []
        for root, dirs, files in os.walk(path):
            for filename in files:
                    file_path = os.path.join(root, filename)
                    file_size = os.path.getsize(file_path)
                    file_size_gb = file_size / (1024 ** 3)
                    files_path.append(file_path)
                    files_size.append(file_size_gb)
        return files_path,files_size

if __name__ == "__main__":
    model = FastModel()
    model.load_model("unsloth/gemma-3-4b-it",load_in_4bit=True)
    dataset = load_dataset("unsloth/Radiology_mini", split = "train")
    dataset=dataset.select(range(5))

    def convert_to_conversation(sample):
        conversation = [
            { "role": "user",
            "content" : [
                {"type" : "image", "image" : sample["image"]},
                {"type" : "text",  "text"  : "สวัสดี"},
                ]
            },
            { "role" : "assistant",
            "content" : [
                # {"type" : "text",  "text"  : "สวัสดีครับคุณ film"} ]
                {"type" : "text",  "text"  : sample["caption"]} ]
            },
        ]
        return { "messages" : conversation }
    
    converted_dataset = [convert_to_conversation(sample) for sample in dataset]

    model.load_dataset(converted_dataset)
    model.trainer(max_steps = 60,logging_steps=1)

    model.start_train()
