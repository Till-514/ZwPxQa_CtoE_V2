import argparse
import csv
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

from transformers import MarianMTModel, MarianTokenizer


CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
INVALID_WINDOWS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
UNDERSCORE_RE = re.compile(r"_+")
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "opus-mt-zh-en"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent / "configs"
REQUIRED_MODEL_FILES = ["config.json", "source.spm", "target.spm", "vocab.json", "pytorch_model.bin"]
MAX_STEM_LENGTH = 96
MAX_FOLDER_NAME_LENGTH = 96
IGNORE_KEYS = ("ignore", "ignored", "exclude", "excluded", "skip", "skipped", "disable", "disabled")
TRUTHY_VALUES = ("1", "true", "yes", "y", "on")

# Edit this list to control which XML config files are read.
# - Use a file name to find matching files anywhere under the target root, for example "macro_config.xml".
# - Use a relative path to read one exact file under the target root, for example "子目录/macro_config.xml".
# - Use an absolute path only when the config file is outside the target root.
# - For Windows absolute paths, use r"C:\path\file.xml", "C:/path/file.xml", or "C:\\path\\file.xml".
# XML files not listed here are ignored.
CONFIG_FILES_TO_READ = [
    # "macro_config.xml",
    # "config/ignore_files.xml",
    # r"C:\ZW3D\zwptoolkits\ZwPxQa\solidworks2019\Configure_AsmDrw.xml",
]


def contains_chinese(text: str) -> bool:
    return bool(CHINESE_RE.search(text))


def sanitize_name(text: str, fallback: str, max_length: int = MAX_STEM_LENGTH) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = text.replace("&", " and ")
    text = INVALID_WINDOWS_CHARS_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9._ -]+", " ", text)
    text = re.sub(r"\s+", "_", text)
    text = text.replace("-", "_")
    text = UNDERSCORE_RE.sub("_", text)
    text = text.strip(" ._")
    text = text or fallback
    if len(text) > max_length:
        text = text[:max_length].rstrip(" ._")
    return text or fallback


def split_file_name(name: str) -> tuple[str, str]:
    if name in {".", ".."}:
        return name, ""
    dot_index = name.rfind(".")
    if dot_index <= 0:
        return name, ""
    return name[:dot_index], name[dot_index:]


def make_unique_name(candidate: str, occupied_lower: set[str], suffix: str = "") -> str:
    candidate = candidate.strip(" ._") or "translated"
    name = f"{candidate}{suffix}"
    if name.lower() not in occupied_lower:
        occupied_lower.add(name.lower())
        return name

    index = 2
    while True:
        name = f"{candidate}_{index}{suffix}"
        if name.lower() not in occupied_lower:
            occupied_lower.add(name.lower())
            return name
        index += 1


def normalize_match_value(text: str) -> str:
    return text.strip().replace("\\", "/").lower()


def normalized_basename(text: str) -> str:
    return normalize_match_value(text).rsplit("/", 1)[-1]


def looks_like_ignore_key(text: str) -> bool:
    lowered = text.lower()
    return any(key in lowered for key in IGNORE_KEYS)


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def add_ignore_value(values: set[str], value: str | None, xml_path: Path, target_root: Path) -> None:
    if not value:
        return
    normalized = normalize_match_value(value)
    if not normalized:
        return

    values.add(normalized)
    values.add(normalized_basename(normalized))

    value_path = Path(value)
    if value_path.is_absolute():
        try:
            values.add(normalize_match_value(value_path.resolve().relative_to(target_root).as_posix()))
        except ValueError:
            pass
        return

    if not value_path.is_absolute():
        absolute_value_path = (xml_path.parent / value_path).resolve()
        try:
            values.add(normalize_match_value(absolute_value_path.relative_to(target_root).as_posix()))
        except ValueError:
            pass


def add_ignore_file_path(values: set[str], value: str | None, xml_path: Path, selected_folder: Path) -> None:
    add_ignore_value(values, value, xml_path, selected_folder)
    if not value:
        return

    value_path = Path(value)
    if value_path.is_absolute():
        absolute_path = value_path.resolve()
    else:
        absolute_path = (selected_folder / value_path).resolve()

    try:
        add_ignore_value(values, absolute_path.relative_to(selected_folder).as_posix(), xml_path, selected_folder)
    except ValueError:
        add_ignore_value(values, str(absolute_path), xml_path, selected_folder)


def resolve_config_entry(entry: str, target_root: Path, extra_config_dirs: list[Path]) -> list[Path]:
    entry = entry.strip()
    if not entry:
        return []

    entry_path = Path(entry)
    if entry_path.is_absolute():
        return [entry_path.resolve()] if entry_path.is_file() else []

    has_path_part = any(separator in entry for separator in ("/", "\\"))
    search_roots = [target_root]
    search_roots.extend(path for path in extra_config_dirs if path.exists())

    if has_path_part:
        paths = []
        for search_root in search_roots:
            candidate = (search_root / entry_path).resolve()
            if candidate.is_file():
                paths.append(candidate)
        return paths

    paths = []
    for search_root in search_roots:
        paths.extend(path.resolve() for path in search_root.rglob(entry) if path.is_file())
    return paths


def iter_xml_configs(target_root: Path, extra_config_dirs: list[Path]) -> list[Path]:
    xml_paths: list[Path] = []
    seen: set[Path] = set()

    for entry in CONFIG_FILES_TO_READ:
        for xml_path in resolve_config_entry(entry, target_root, extra_config_dirs):
            if xml_path.suffix.lower() != ".xml":
                continue
            if xml_path in seen:
                continue
            seen.add(xml_path)
            xml_paths.append(xml_path)

    return xml_paths


def element_is_ignored(element: ElementTree.Element) -> bool:
    if looks_like_ignore_key(element.tag):
        return True

    for attr_name, attr_value in element.attrib.items():
        if looks_like_ignore_key(attr_name):
            value = attr_value.strip().lower()
            if not value or value in TRUTHY_VALUES:
                return True
    return False


def inside_ignore_container(element: ElementTree.Element, ignored_container_depth: int) -> bool:
    return ignored_container_depth > 0 and element.text is not None and element.text.strip() != ""


def collect_values_from_element(element: ElementTree.Element) -> list[str]:
    values: list[str] = []
    if element.text and element.text.strip():
        values.append(element.text.strip())
    values.extend(value.strip() for value in element.attrib.values() if value.strip())
    return values


def collect_ignore_files_from_xml(tree: ElementTree.ElementTree) -> list[str]:
    root = tree.getroot()
    values: list[str] = []

    for element in root.iter():
        if xml_local_name(element.tag) != "ignorefiles":
            continue
        for child in list(element):
            if xml_local_name(child.tag) != "file":
                continue
            if child.text and child.text.strip():
                values.append(child.text.strip())
            for attr_name in ("path", "file", "name"):
                attr_value = child.attrib.get(attr_name)
                if attr_value and attr_value.strip():
                    values.append(attr_value.strip())

    return values


def load_ignored_items(target_root: Path, extra_config_dirs: list[Path]) -> tuple[set[str], list[Path]]:
    ignored_items: set[str] = set()
    xml_paths = iter_xml_configs(target_root, extra_config_dirs)

    for xml_path in xml_paths:
        try:
            tree = ElementTree.parse(xml_path)
        except ElementTree.ParseError as error:
            print(f"Warning: cannot parse XML config {xml_path}: {error}", file=sys.stderr)
            continue

        for value in collect_ignore_files_from_xml(tree):
            add_ignore_file_path(ignored_items, value, xml_path, target_root)

        root = tree.getroot()
        stack: list[tuple[ElementTree.Element, int]] = [(root, 1 if element_is_ignored(root) else 0)]

        while stack:
            element, ignored_container_depth = stack.pop()
            if element_is_ignored(element):
                for value in collect_values_from_element(element):
                    add_ignore_value(ignored_items, value, xml_path, target_root)
            elif inside_ignore_container(element, ignored_container_depth):
                for value in collect_values_from_element(element):
                    add_ignore_value(ignored_items, value, xml_path, target_root)

            ignore_attr_is_true = any(
                looks_like_ignore_key(attr_name) and attr_value.strip().lower() in TRUTHY_VALUES
                for attr_name, attr_value in element.attrib.items()
            )
            if ignore_attr_is_true:
                for attr_name, attr_value in element.attrib.items():
                    if not looks_like_ignore_key(attr_name):
                        add_ignore_value(ignored_items, attr_value, xml_path, target_root)

            child_depth = ignored_container_depth + 1 if element_is_ignored(element) else ignored_container_depth
            stack.extend((child, child_depth) for child in list(element))

    return ignored_items, xml_paths


def is_ignored_match(candidate: str, ignored_items: set[str]) -> bool:
    candidate = normalize_match_value(candidate)
    candidate_name = normalized_basename(candidate)
    candidate_stem = normalize_match_value(split_file_name(candidate_name)[0])

    for ignored_item in ignored_items:
        ignored_item = normalize_match_value(ignored_item)
        ignored_name = normalized_basename(ignored_item)
        ignored_stem = normalize_match_value(split_file_name(ignored_name)[0])

        if candidate in {ignored_item, ignored_name, ignored_stem}:
            return True
        if candidate_name in {ignored_item, ignored_name}:
            return True
        if candidate_stem and candidate_stem == ignored_stem:
            return True
        if "/" in ignored_item and candidate.endswith("/" + ignored_item):
            return True

    return False


def is_macro_file(original_rel: Path, original_name: str, ignored_items: set[str]) -> str:
    candidates = {
        normalize_match_value(original_rel.as_posix()),
        normalize_match_value(original_name),
        normalize_match_value(split_file_name(original_name)[0]),
    }
    return "0" if any(is_ignored_match(candidate, ignored_items) for candidate in candidates) else "1"


class OfflineTranslator:
    def __init__(self, model_path: Path) -> None:
        self.model_path = resolve_model_path(model_path)
        self.tokenizer = MarianTokenizer.from_pretrained(str(self.model_path), local_files_only=True)
        self.model = MarianMTModel.from_pretrained(str(self.model_path), local_files_only=True)
        self.cache: dict[str, str] = {}

    def translate(self, text: str) -> str:
        if text not in self.cache:
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
            outputs = self.model.generate(**inputs, max_length=128)
            self.cache[text] = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return self.cache[text]


def translated_child_name(child: Path, translator: OfflineTranslator) -> str:
    if child.is_dir():
        translated = translator.translate(child.name)
        return sanitize_name(translated, fallback="folder", max_length=MAX_FOLDER_NAME_LENGTH)

    stem, suffix = split_file_name(child.name)
    translated = translator.translate(stem)
    return sanitize_name(translated, fallback="file", max_length=MAX_STEM_LENGTH) + suffix


def build_plan(root: Path, translator: OfflineTranslator, ignored_items: set[str]) -> list[dict[str, str]]:
    rename_names: dict[Path, str] = {}
    rows: list[dict[str, str]] = []

    directories = [root]
    directories.extend(path for path in root.rglob("*") if path.is_dir())

    for directory in sorted(directories, key=lambda p: len(p.relative_to(root).parts)):
        children = list(directory.iterdir())
        occupied_lower = {child.name.lower() for child in children if not contains_chinese(child.name)}

        for child in sorted(children, key=lambda p: (not p.is_dir(), p.name.lower())):
            if not contains_chinese(child.name):
                continue

            raw_candidate = translated_child_name(child, translator)
            if child.is_file():
                candidate_stem, suffix = split_file_name(raw_candidate)
                new_name = make_unique_name(candidate_stem, occupied_lower, suffix=suffix)
            else:
                new_name = make_unique_name(raw_candidate, occupied_lower)

            rename_names[child] = new_name

    for original_abs, new_name in sorted(rename_names.items(), key=lambda item: item[0].relative_to(root).parts):
        original_rel = original_abs.relative_to(root)
        new_parts = [rename_names.get(root / Path(*original_rel.parts[: idx + 1]), part) for idx, part in enumerate(original_rel.parts)]
        new_rel = Path(*new_parts)
        rows.append(
            {
                "type": "directory" if original_abs.is_dir() else "file",
                "original_relative_path": original_rel.as_posix(),
                "new_relative_path": new_rel.as_posix(),
                "original_name": original_abs.name,
                "new_name": new_name,
                "is_macro_file": is_macro_file(original_rel, original_abs.name, ignored_items),
                "status": "planned",
            }
        )

    return rows


def write_mapping_csv(root: Path, rows: list[dict[str, str]]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mapping_path = root / f"rename_mapping_{timestamp}.csv"
    fieldnames = ["original_name", "new_name", "original_relative_path", "is_macro_file"]

    with mapping_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    return mapping_path


def load_mapping_csv(mapping_path: Path) -> list[dict[str, str]]:
    with mapping_path.open("r", newline="", encoding="utf-8-sig") as file:
        rows = []
        for row in csv.DictReader(file):
            row.setdefault("original_relative_path", row.get("original_name", ""))
            row.setdefault("new_relative_path", row.get("new_name", ""))
            row.setdefault("status", "planned")
            rows.append(row)
        return rows


def csv_path_to_path(text: str) -> Path:
    return Path(*[part for part in text.replace("\\", "/").split("/") if part])


def has_required_model_files(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in REQUIRED_MODEL_FILES)


def resolve_model_path(model_path: Path) -> Path:
    candidates = [
        model_path,
        model_path / "opus-mt-zh-en",
        model_path / "models" / "opus-mt-zh-en",
    ]

    for candidate in candidates:
        if has_required_model_files(candidate):
            return candidate

    if model_path.is_dir():
        for candidate in model_path.rglob("config.json"):
            folder = candidate.parent
            if has_required_model_files(folder):
                return folder

    missing = [name for name in REQUIRED_MODEL_FILES if not (model_path / name).is_file()]
    raise FileNotFoundError(
        "Cannot find a complete opus-mt-zh-en model folder.\n"
        f"Checked from: {model_path}\n"
        f"Missing at this exact path: {', '.join(missing)}\n"
        "The model path must point to the folder containing config.json, source.spm, "
        "target.spm, vocab.json, and pytorch_model.bin."
    )


def safe_new_name(row: dict[str, str]) -> str:
    raw_name = row.get("new_name") or csv_path_to_path(row["new_relative_path"]).name
    stem, suffix = split_file_name(raw_name)
    max_length = MAX_FOLDER_NAME_LENGTH if row.get("type") == "directory" else MAX_STEM_LENGTH
    return sanitize_name(stem, fallback="renamed", max_length=max_length) + suffix


def execute_rows(root: Path, rows: list[dict[str, str]]) -> None:
    executable_rows = [row for row in rows if row.get("original_relative_path") != row.get("new_relative_path")]
    executable_rows.sort(key=lambda row: len(csv_path_to_path(row["original_relative_path"]).parts), reverse=True)

    for row in executable_rows:
        original_rel = csv_path_to_path(row["original_relative_path"])
        src = root / original_rel
        dst = src.with_name(safe_new_name(row))

        if not src.exists():
            row["status"] = "missing_source"
            continue
        if dst.exists():
            row["status"] = "target_exists"
            continue

        try:
            src.rename(dst)
        except OSError as error:
            row["status"] = f"error: {error}"
            continue

        row["new_name"] = dst.name
        row["status"] = "renamed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rename Chinese files and folders to English with an offline local translation model.")
    parser.add_argument("root", help="Root folder to scan.")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH), help="Local model directory. Defaults to ./models/opus-mt-zh-en.")
    parser.add_argument(
        "--config-dir",
        action="append",
        default=[],
        help="Extra root folder for resolving CONFIG_FILES_TO_READ entries. Can be used multiple times.",
    )
    parser.add_argument("--execute", action="store_true", help="Actually rename files and folders. Without this flag, only a CSV plan is created.")
    return parser.parse_args()


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    args = parse_args()
    root = Path(args.root).resolve()
    model_path = Path(args.model_path).resolve()
    extra_config_dirs = [Path(config_dir).resolve() for config_dir in args.config_dir]

    if not root.is_dir():
        print(f"Root folder does not exist: {root}", file=sys.stderr)
        return 2

    try:
        translator = OfflineTranslator(model_path)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 2
    ignored_items, xml_paths = load_ignored_items(root, extra_config_dirs)
    rows = build_plan(root, translator, ignored_items)

    if args.execute:
        execute_rows(root, rows)

    mapping_path = write_mapping_csv(root, rows)
    action = "Executed" if args.execute else "Dry-run"
    print(f"{action}: {len(rows)} item(s). Mapping saved to: {mapping_path}")
    print(f"XML configs scanned from CONFIG_FILES_TO_READ: {len(xml_paths)} file(s).")
    print(f"Ignored entries loaded from XML: {len(ignored_items)} item(s).")
    for xml_path in xml_paths:
        print(f"  - {xml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
