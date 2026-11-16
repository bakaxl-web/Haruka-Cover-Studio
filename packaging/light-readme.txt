Haruka Cover Studio 轻量版

1. 完整解压压缩包，双击 Haruka Cover Studio Light.exe。
2. 首次启动会打开“运行环境设置”并自动查找常见目录，找到的候选路径会填入空白项。
   也可点击“自动查找”重试，在输入框下拉候选中切换，或手动选择电脑上已有的：
   - RVC 推理 Python：现有环境中的 python.exe。
   - RVC 代码目录：与声线模型配套，含 infer/cli.py、infer/vc 和 assets。
   - FFmpeg：ffmpeg.exe。
   - 后端 Python：可留空使用推理 Python，也可选单独的环境。
3. 点击“检查并使用”。自动查找不会扫描整盘、覆盖已有选择或自动启用未经检查的环境。
   未通过时按提示重新选择兼容环境或补齐缺失文件。
4. 在“模型管理”导入声线权重和配套索引。不同模型需要不同代码时，单独指定专用 RVC 目录。
5. 导入干声、选择声线并转换；伴奏可选，支持拖入。先用短片段验证模型与代码匹配。

运行要求
- Python 3.10 或以上。
- 后端需 FastAPI、Uvicorn、Pydantic 2、NumPy、SciPy、SoundFile。
- 推理需兼容的 PyTorch、Librosa、Faiss 等依赖，以及当前 Haruka 推理接口。
- 基础模型为代码目录 assets/hubert_base 下的本地 Transformers HuBERT/ContentVec，
  以及 assets/rmvpe/rmvpe.pt；这些文件不在本包中。
- 普通 RVC 整合包不保证支持 v6b.1-D / v6e。需要模型提供者交付配套代码与模型资产。

本包仅含桌面程序、后端和推理衔接脚本，不含 Python、PyTorch、CUDA 运行库、FFmpeg、
RVC 外部代码、声线权重、索引或基础模型。程序不会自动安装或升级你的环境。
环境配置保存在当前用户的应用数据目录；移动或删除外部环境后需重新选择。
作品默认保存到“文档/Haruka Cover Studio/outputs”，可从任务详情打开。
环境检查只验证依赖、接口与基础文件，具体模型兼容性和音质仍须实际试转。
