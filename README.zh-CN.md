# mlx-serve-alp

[English](README.md)

为 Apple Silicon 上的原生 [MLX-Serve](https://github.com/ddalcu/mlx-serve)
增加 ALP 0.3.0 动作生成接口：`POST /v1/alp/chat/completions`。
六个操作的协议契约、目录和最终校验复用
[vllm-alp](https://github.com/omni-runtime/vllm-alp) 与 `alp-schema-mcp`。

MLX-Serve 是原生二进制，没有 vLLM 的 Python endpoint plugin 接口。
本项目通过带鉴权的 loopback HTTP 连接引擎；推理依旧由 MLX-Serve 完成。
适配层不加载权重、不执行工具，也不承担宿主 Runtime 的授权职责。

## 安装与运行

**`alp_schema_mcp` 和 `vllm-alp` 两个依赖仓库保持私有。使用者必须自行取得
访问权限或经授权的 wheel；仅克隆此公开仓库无法运行。**
本仓库不分发依赖源码、协议契约或原始测试包，详见 [依赖说明](docs/dependencies.md)。

需要 Python 3.12+、MLX-Serve 26.9.6，以及对应模型权重。
先安装 `alp-schema-mcp==0.3.0` 和 `vllm-alp==0.2.0` 的 wheel 或源码，
再运行 `pip install -e '.[test]'`。详细命令见英文 README。

`examples/config.json` 集中配置引擎地址、模型名称和目录；示例目录全部是
虚构测试数据。部署时替换为宿主发布的真实契约。
密钥只通过 `MLX_ALP_API_KEY`、`MLX_ALP_ENGINE_KEY` 环境变量提供。
引擎只监听 loopback；`/health` 以外的适配层接口都要求 Bearer 鉴权。

```bash
mlx-serve-alp check --config examples/config.json
mlx-serve-alp serve --config examples/config.json --host 127.0.0.1 --port 11237
```

宿主服务可使用 `scripts/service.py` 和 `examples/settings.json`。
配置文件记录路径与密钥文件引用，不记录密钥内容。

## 行为与边界

模型直接生成 canonical JSON。`raw` 和流式 delta 保留原始字符；
`alp.raw_format=canonical`，不会把它伪装成模型生成的 tagged 格式。
最终接口与 vllm-alp 一样返回 `message.agent_calls`。

流式结果只有 `agent_call.completed` 才代表完整输出已通过静态校验；
截断、尾随内容、多动作、目录参数错误等产生 `agent_call.failed`。
所有结果都保持 `executed=false`、`authorized=false`。

MLX-Serve 的 JSON mask 只支持部分约束。联合分支关联、正则、数值范围等
在完整输出上再次严格验证，并在 `alp.residual_checks` 报告。
约束投影不是完整 XGrammar 等价实现，不能保证生成阶段满足全部协议约束。

服务端目录可配置 `payload_constraints`，指定任务要求的必填字段和固定值，
只能收窄现有协议与目录。客户端不能直接覆盖约束，详见[任务约束](docs/task-constraints.md)。
提示词渲染与 vllm-alp 共享。`compact_prompt: true` 可裁剪未引用定义并保留说明；
`explicit_definition_output: true` 可要求生成时显式填写 `output`。两项默认关闭，
应针对实际模型评估。最终校验仍兼容协议默认值；参数 Schema 允许空对象时，
Agent 调用可以省略参数。

## 验证

```bash
pytest -q
ruff check src tests scripts
python -m build
python scripts/run_producer.py --suite /path/to/alp_schema_mcp \
  --base-url http://127.0.0.1:11237 --model local/alp \
  --codec canonical --output reports/live
```

设置 `ALP_API_KEY` 后，runner 会发送原始 test-case 的 20 道任务，
记录真实原始输出并调用原包 checker。它不会把 golden 答案放进提示词，
不会自动修复、重试或丢弃失败结果。操作类型由测试请求明确选择。
静态样本、真实生成、Runtime 执行是三类独立证据。

请针对实际任务验证所选模型：符合 Schema 的动作仍可能填写错误的参数。
验证报告和原始证据仅保留在本地，不提交或推送到此仓库。
参见 [贡献指南](CONTRIBUTING.md)、[安全边界](SECURITY.md)。
代码采用 [Apache-2.0](LICENSE)；模型和引擎分别遵循其自身许可。
