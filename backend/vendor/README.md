# vendor（只读副本）

本目录是从 `Haruka-Voice-Forge` 复制的推理模块，**只读使用，不在此处修改算法**。
Voice-Forge 仍是唯一事实来源；如需升级，重新复制并更新本文件的哈希记录。

| 文件 | 来源 | SHA-256 |
| --- | --- | --- |
| `run_rvc_aligned.py` | `Haruka-Voice-Forge/run_rvc_aligned.py` | `d71240161db59931a0b952bfbe17e14c059da952fbb4c94e13a562d0c851c100` |
| `rvc_runtime.py` | `Haruka-Voice-Forge/rvc_runtime.py` | `7cb107edf79bd334a95bfc8b408c249de7daaf7c98d10becadff5b7494da62f9` |
| `rvc_v6b_compat.py` | `Haruka-Voice-Forge/rvc_v6b_compat.py` | `698ee3a22f402b04574b98f1eb111551aa3d0466c66644c234fab57c79f931bf` |
| `mix_vocal_plus_gain.py` | `Haruka-Voice-Forge/mix_vocal_plus_gain.py` | `267682401fb9519054ae9513a5a5394546fa0a0b4c9f9a21695aacfac688cdab` |

升级流程：

1. 从 Voice-Forge 重新复制同名文件；
2. 用 `Get-FileHash -Algorithm SHA256` 重新计算并更新上表；
3. 复跑 `outputs` 中的基线任务，确认 40 kHz / 44.1 kHz / 混音三个产物的 SHA-256 仍与历史一致。

发布适配：0.2.3 仅将 run_rvc_aligned.py 的开发机默认路径改为项目内 runtime/rvc-app；外部代码目录仍由参数指定，推理算法不变。
