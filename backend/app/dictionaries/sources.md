# 内置保护词典的来源说明

本项目只把小型、可审计的 starter 词典放进运行时，不在运行时联网下载第三方词库。

词法分层和标签命名参考：

1. [jieba](https://github.com/fxsjy/jieba)：开源中文分词工具，提供 jieba.posseg 的 POS 接口。
2. [HanLP](https://github.com/hankcs/HanLP)：开源 NLP 工具包，提供分词、词性、NER 等模块边界。
3. [Baidu LAC](https://github.com/baidu/lac)：开源中文词法分析工具，提供分词、词性和实体标签。

这些项目是实现接口和风险边界的参考，不代表本项目复制其模型权重或完整词库。运行时所用的 starter 保护词、风险词和安全候选见 default_protected.json，用户导入的 .txt/.csv 词典具有最高优先级。

发行包必须继续携带各依赖的许可证与 NOTICE；Qwen3.5-2B 的 Apache-2.0 许可证见模型目录中的 LICENSE。

