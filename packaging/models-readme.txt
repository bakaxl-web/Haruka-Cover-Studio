Haruka Cover Studio 轻量模型版

内含五个春香推理版本：v6a e200、v6b.1-D e400、v6b.2 e190、v6b.2 e200、v6e e90。
v6a 与 e400 带配套索引；v6b.2 与 v6e 没有配套索引，默认关闭检索。
各模型配套的 RVC 代码、HuBERT/ContentVec 和 RMVPE 基础文件已包含。
包内含 SHA-256 清单及原推理代码许可文件。技术打包通过不代表新候选音质已验收。

1. 将压缩包完整解压到可写目录，双击 Haruka Cover Studio Models.exe。
2. 首次启动自动查找电脑上已有 Python 与 FFmpeg，RVC 代码目录已指向随包代码。
3. 点击“检查并使用”，环境通过后在模型列表选择声音，不需要再逐个导入模型。
4. 导入干声，伴奏可选；先用短片段试转，再制作整曲。
5. 解压路径可以改变，随包模型和代码会按新位置重新解析。

仍需电脑已有兼容的 Python、PyTorch/CUDA 等依赖，以及 FFmpeg；本包不会自动安装或升级软件。
模型预设使用“自动”音高设备，程序会按可用设备处理；具体速度取决于电脑硬件。
模型与代码文件请保留原有目录结构，不要只复制 exe 或单个权重文件。
输出默认在“文档/Haruka Cover Studio/outputs”，可在任务详情中打开。
当前质量状态及文件完整性见 resources/model-bundle/manifest.json。
