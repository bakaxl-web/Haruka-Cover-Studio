# Haruka Cover Studio

Windows 本地 AI 翻唱工作台。导入已分离的人声，选择 RVC 声线，调整升降调，再试听、混音和导出。

## 下载

到 [Releases](https://github.com/bakaxl-web/Haruka-Cover-Studio/releases) 下载 Windows x64 ZIP，完整解压后打开 `.exe`。不要直接在压缩包里运行。

| 版本 | 包含内容 | 适用情况 |
| --- | --- | --- |
| Light | 桌面程序、后端和使用说明 | 已有声线与配套 RVC 代码 |
| Light-Models | 程序、五个春香声线、配套代码、HuBERT/RMVPE、两份索引 | 希望使用随包声线 |

两版均不携带 Python、PyTorch、FFmpeg，需要复用已有环境。首次启动可自动查找，也可手动选择；只有“检查并使用”通过后才保存。不会自动安装或升级其他软件的依赖。

## 功能

- 浅色桌面界面，人声和伴奏都可拖拽或点击导入。
- 干声可单独转换；可选伴奏混音，人声增益可调。
- −12 至 +12 半音升降调，保留人声时间轴。
- 模型导入、配套推理代码选择、参数调整和环境诊断。
- 原声与产物试听、WAV/FLAC 导出、历史任务查看。
- 片段试唱：波形拖选或输入起止时间，默认前 20 秒，可选 1–60 秒；带前后上下文推理后精确裁切。
- 多模型对比：同一片段依次试唱，切换时保留播放位置；可匹配试听音量，再一键排队制作整首。
- 运行设备可选自动、CPU 或可用的 NVIDIA CUDA 显卡，任务详情记录实际设备。
- 批量与队列：多首干声、逐首伴奏、每首多个模型；串行执行，支持取消及失败重试。

不包含 MSST 或人声分离；请先准备干声和伴奏。直接输入支持 WAV、FLAC、MP3、OGG，暂不声明 M4A/AAC 支持。

## 快速开始

1. 解压后运行程序，选择或自动查找推理 Python、FFmpeg。模型版会自动定位随包 RVC 代码。
2. 后端 Python 可以与推理环境共用；若依赖冲突，单独选择后端环境。点击“检查并使用”。
3. 导入干声，选择声线。纯轻量版需先在“模型管理”导入权重及配套代码。
4. 如需混音，添加与干声采样率、帧数一致的双声道伴奏。升降调作用于转换人声，伴奏不会自动移调。
5. 开始转换，完成后试听并导出。默认产物位于系统文档目录下 `Haruka Cover Studio/outputs`。

想先比较声音，可切换“片段试唱 / 模型对比”，选择区间与 2–8 个模型。音量匹配按 RMS 调整试听副本并限制峰值，不改原始产物或导出；采用模型制作整首时沿用该试听任务的音源、升降调和设备。批量提交每次最多 100 个转换任务，设置在提交时保存，后续表单修改不会影响已排队任务。退出应用会中断未完成任务，下次启动后可手动重试。

模型版内置：v6a e200、v6b.1-D e400、v6b.2 e190、v6b.2 e200、v6e e90。v6a/e400 使用配套索引，另三版默认关闭检索。模型文件采用相对路径，移动解压目录后仍可识别。不同架构需要各自配套代码，普通 RVC WebUI 不保证兼容这些模型。

## 环境与验证边界

- Windows x64；环境检查要求 Python 3.10+，本机验证使用 Python 3.12、PyTorch 2.7.1+cu118。
- 推理环境需有 PyTorch、NumPy、SciPy、SoundFile、librosa、FAISS、praat-parselmouth，以及配套 RVC 代码要求的依赖。
- 后端需 FastAPI、Uvicorn、Pydantic 2 等，清单见 `backend/requirements.txt`。
- NVIDIA CUDA 环境用于加速。五个随包模型已在 CPU 完成六秒试转；显卡、驱动和外部环境仍须在使用者电脑验证。
- 0.3.0 已验证 e400/e90 的 CPU 片段转换，以及 e400 的 RTX 4060 CUDA 片段转换、伴奏裁切和重采样。AMD / DirectML 加速暂未接入，AMD 电脑可选择 CPU；多卡选择仍需在对应硬件上验证。
- e400/e90 的原调及 ±3 半音已做短样本验证。短样本、可解码音频与自动指标不代表完整音质验收。
- 当前程序未做代码签名；环境搜索有目录数量和深度限制，未找到时可手动选择。

## 开发与构建

需要 Node.js 20+ 和 Python。首次安装：

```powershell
npm ci
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm run dev
```

开发模式可通过 `HARUKA_LIGHTWEIGHT=1` 使用环境设置；也可设置 `HARUKA_BACKEND_PYTHON`、`HARUKA_INFERENCE_PYTHON`、`HARUKA_RVC_APP_ROOT`、`HARUKA_FFMPEG` 指定外部环境。源码不包含作者本机配置或声线模型。

```powershell
npm run test:runtime
npm run test:backend
npx tsc --noEmit
npm run build:light
```

模型版先用 `packaging/build-model-bundle.py --spec <本机模型清单.json>` 生成 `.build/model-bundle`，再运行 `npm run build:models`。模型清单须提供实际源路径、版本和 SHA-256；本机清单不提交 Git。构建器校验权重和索引复制结果。

## 项目边界与许可

这个仓库维护桌面应用和推理编排，不负责训练、数据集或质量评估实验。模型、音频、运行环境和发布 ZIP 不进入 Git 历史，发行包在 Releases 单独提供。

原创应用代码使用 [MIT](LICENSE)；第三方代码及基础模型保留原许可，见 [第三方说明](THIRD_PARTY_NOTICES.txt) 和 `licenses/`。声线模型不自动适用应用源码的 MIT 许可。本项目不是相关角色或作品的官方产品。

遇到问题可在 [Issues](https://github.com/bakaxl-web/Haruka-Cover-Studio/issues) 提交版本、操作步骤和必要日志；分享日志前请去掉私人路径及敏感信息。
