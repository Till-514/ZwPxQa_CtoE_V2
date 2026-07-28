from pathlib import Path

from transformers import MarianMTModel, MarianTokenizer


BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "opus-mt-zh-en"


def main() -> None:
    tokenizer = MarianTokenizer.from_pretrained(str(MODEL_PATH), local_files_only=True)
    model = MarianMTModel.from_pretrained(str(MODEL_PATH), local_files_only=True)

    text = "项目预算报告"
    inputs = tokenizer(text, return_tensors="pt")
    outputs = model.generate(**inputs, max_length=64)
    result = tokenizer.decode(outputs[0], skip_special_tokens=True)
    print(result)


if __name__ == "__main__":
    main()
