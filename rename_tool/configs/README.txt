The script only reads XML files listed in CONFIG_FILES_TO_READ at the top of rename_chinese_paths.py.
Other XML files are ignored.

Supported CONFIG_FILES_TO_READ examples:

"macro_config.xml"
  Finds files named macro_config.xml anywhere under the target root.

"config/ignore_files.xml"
  Reads config/ignore_files.xml under the target root.

"D:/configs/ignore_files.xml"
  Reads one absolute XML file.

This folder can be used as an extra search root with:

python rename_chinese_paths.py "target_folder" --config-dir ".\configs"

Files or folders matched by ignore/exclude/skip/disabled rules are marked as 0 in the CSV.
Other renamed items are marked as 1.

Supported examples:

<IgnoreFiles>
  <Ignore>示例文件.csv</Ignore>
  <Exclude>子目录/示例文件.csv</Exclude>
  <File name="示例文件夹" ignore="true" />
</IgnoreFiles>

Only files ending with .xml and listed in CONFIG_FILES_TO_READ are read by the script.
