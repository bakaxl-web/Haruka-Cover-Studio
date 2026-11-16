# vendor（只读副本）

本目录基于 `Haruka-Voice-Forge` 的推理模块，保持转换算法不变；应用专用的路径与设备适配记录在下方。
算法升级应从 Voice-Forge 同步，并保留应用适配、更新本文件的哈希记录。

| 文件 | 来源 | SHA-256 |
| --- | --- | --- |
| `run_rvc_aligned.py` | `Haruka-Voice-Forge/run_rvc_aligned.py` + 应用设备适配 | `1f7eee3b9654ed59a2de1b85aae946f0427dd10f48ca12d7646616f4fa7f631e` |
| `rvc_runtime.py` | `Haruka-Voice-Forge/rvc_runtime.py` | `7cb107edf79bd334a95bfc8b408c249de7daaf7c98d10becadff5b7494da62f9` |
| `rvc_v6b_compat.py` | `Haruka-Voice-Forge/rvc_v6b_compat.py` | `698ee3a22f402b04574b98f1eb111551aa3d0466c66644c234fab57c79f931bf` |
| `mix_vocal_plus_gain.py` | `Haruka-Voice-Forge/mix_vocal_plus_gain.py` | `267682401fb9519054ae9513a5a5394546fa0a0b4c9f9a21695aacfac688cdab` |

升级流程：

1. 从 Voice-Forge 重新复制同名文件；
2. 用 `Get-FileHash -Algorithm SHA256` 重新计算并更新上表；
3. 复跑 `outputs` 中的基线任务，确认 40 kHz / 44.1 kHz / 混音三个产物的 SHA-256 仍与历史一致。

发布适配：0.2.3 仅将 run_rvc_aligned.py 的开发机默认路径改为项目内 runtime/rvc-app；外部代码目录仍由参数指定，推理算法不变。

0.3.0 增加可选 `--device`（auto/cpu/cuda:N），在加载模型前统一生成器、HuBERT、RMVPE 的设备配置，并记录 `actual_device`；省略该参数时保留旧行为。CPU 使用 FP32，应用自动模式不启用未验证的 DirectML。e400/e90 CPU 与 e400 CUDA 的真实片段转换已验证；多卡硬件未实测。
