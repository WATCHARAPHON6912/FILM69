from setuptools import setup, find_packages

setup(
    name="film69",
    version="0.4.2",
    description="",  # Add your package's description here
    author="Watcharaphon Pamayayang",
    author_email="filmmagic45@gmail.com",
    url="https://github.com/watcharaphon6912",
    packages=find_packages(),
    install_requires=[
        # List base dependencies here if needed
        # "numpy",
    ],
    extras_require={
        "all": [
            "setuptools",
            "setuptools-scm",
            "packaging",
            "tyro",
            "transformers>=4.44.2",
            "datasets",
            "sentencepiece",
            "tqdm",
            "psutil",
            "wheel",
            "numpy",
            "accelerate",
            "trl",
            "peft",
            "protobuf",
            "huggingface-hub",
            "hf-transfer",
            "bitsandbytes",
            "xformers",
            "ninja",
            "minimalmodbus",
            "sentence-transformers",
            "llama-index-vector-stores-milvus",
            "llama-index",
            "llama-index-embeddings-huggingface",
            "pymilvus",
            "openai",
            "pandas",
            "openpyxl",
            "triton",
            "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git",
            "chromadb"
        ],
        "rag": [
            "pymilvus",
            "openai",
            "transformers>=4.44.2",
            "sentence-transformers",
            "numpy",
            "pandas",
            "openpyxl",
            "chromadb"
        ],
    },
    python_requires=">=3.7",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    setup_requires=["setuptools", "wheel"]
)
