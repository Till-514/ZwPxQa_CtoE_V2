# 中文路径批量英文重命名工具

本工具用于递归扫描一个目标文件夹，把包含中文的文件名和文件夹名翻译成英文，并在目标文件夹根目录输出 CSV 记录表。

目录结构不会被重排。脚本只改名称，不移动文件。

## 运行环境

内网机器需要已安装 Python 依赖：

```powershell
python -m pip install torch transformers sentencepiece sacremoses huggingface_hub
```

本地离线翻译模型需要使用 `Helsinki-NLP/opus-mt-zh-en`。如果模型已经放到工具目录外面，运行时必须通过 `--model-path` 指定模型目录。

模型目录必须包含这些文件：

```text
config.json
source.spm
target.spm
vocab.json
pytorch_model.bin
```

## 脚本位置

```text
rename_tool/
  rename_chinese_paths.py
  rename_chinese_paths_V2.py
  test_translate.py
```

当前主要使用：

```text
rename_tool/rename_chinese_paths.py
```

## 配置忽略文件

`rename_chinese_paths.py` 通过脚本顶部的 `CONFIG_FILES_TO_READ` 指定要读取的 XML 配置文件。

示例：

```python
CONFIG_FILES_TO_READ = [
    r"C:\ZW3D\zwptoolkits\ZwPxQa\solidworks2019\开发人员图纸\Configure_AsmDrw.xml",
    r"C:\ZW3D\zwptoolkits\ZwPxQa\solidworks2019\开发人员图纸\Configure_Part.xml",
]
```

注意 Windows 路径必须写成以下任一种：

```python
r"C:\path\file.xml"
"C:/path/file.xml"
"C:\\path\\file.xml"
```

不要直接写：

```python
"C:\path\file.xml"
```

否则 `\n`、`\t` 等可能被 Python 当成转义字符。

XML 中支持这种格式：

```xml
<IgnoreFiles>
  <File>开发人员图纸\AsmDrw\AsmMirror\装配镜向.SLDASM</File>
</IgnoreFiles>
```

匹配到的文件会在 CSV 中标记：

```csv
is_macro_file = 0
```

未匹配到的文件标记：

```csv
is_macro_file = 1
```

## 先干跑

干跑只生成 CSV，不真正改名。

```powershell
cd C:\Users\GESIC\Desktop\xuhongtao\ZwPxQa_CtoE\rename_tool

python .\rename_chinese_paths.py "C:\ZW3D\zwptoolkits\ZwPxQa" --model-path "D:\models\opus-mt-zh-en"
```

输出 CSV 会保存在目标文件夹根目录，例如：

```text
C:\ZW3D\zwptoolkits\ZwPxQa\rename_mapping_20260728_101500.csv
```

CSV 表头：

```csv
original_name,new_name,original_relative_path,is_macro_file
```

字段说明：

```text
original_name
原始文件名或文件夹名

new_name
翻译后的英文名

original_relative_path
原文件或文件夹相对目标根目录的位置

is_macro_file
0 = XML 配置中忽略，不作为宏文件
1 = 未忽略，作为宏文件
```

## 调试忽略项

如果 XML 已经读到，但 CSV 没有标记为 `0`，加 `--debug-ignore` 查看解析结果：

```powershell
python .\rename_chinese_paths.py "C:\ZW3D\zwptoolkits\ZwPxQa" --model-path "D:\models\opus-mt-zh-en" --debug-ignore
```

重点看输出：

```text
XML configs scanned from CONFIG_FILES_TO_READ: N file(s).
Ignored entries loaded from XML: N item(s).
```

如果 XML 数量是 0，说明 `CONFIG_FILES_TO_READ` 路径没写对。

如果忽略项数量是 0，说明 XML 结构没有被解析出来。

## 正式执行

确认干跑 CSV 没问题后，再加 `--execute`：

```powershell
python .\rename_chinese_paths.py "C:\ZW3D\zwptoolkits\ZwPxQa" --model-path "D:\models\opus-mt-zh-en" --execute
```

正式执行时脚本按自下往上的顺序重命名，避免父目录先改名后找不到子文件。

## 重要注意事项

执行前建议先备份目标目录，或至少先保留 dry-run 生成的 CSV。

如果已经执行过一次，文件名已经变成英文，再次运行只会处理仍然包含中文的文件或文件夹。

如果模型放在外部目录，不要依赖默认模型路径。每次运行都显式传：

```powershell
--model-path "D:\models\opus-mt-zh-en"
```
