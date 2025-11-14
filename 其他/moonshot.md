# API 错误代码参考
# API接口说明：https://api.moonshot.cn/v1/chat/completions
| HTTP 状态代码 | 错误类型                     | 错误信息                                                                                             | 详细描述                                                                                           |
| ------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 400           | content_filter               | 该请求被拒绝，因为它被认为是高风险的                                                                 | 内容审查拒绝，您的输入或生成内容可能包含不安全或敏感内容，请您避免输入易产生敏感内容的提示语，谢谢 |
| 400           | invalid_request_error        | 请求无效：{error_details}                                                                            | 请求无效，通常是您请求格式错误或者缺少必要参数，请检查后重试                                       |
| 400           | invalid_request_error        | 输入令牌长度过长                                                                                     | 请求中的 tokens 长度过长，请求不要超过模型 tokens 的最长限制                                       |
| 400           | invalid_request_error        | 您的请求超出了模型令牌限制：{max_model_length}                                                       | 请求的 tokens 数和设置的 max_tokens 加和超过了模型规格长度，请检查请求体的规格或选择合适长度的模型 |
| 400           | invalid_request_error        | 目的无效：仅接受"文件提取"                                                                           | 请求中的目的（目的）不正确，当前只接受 'file-extract'，请修改后重新请求                            |
| 400           | invalid_request_error        | 文件过大，最大文件大小为100MB，请确认并重新上传文件                                                  | 上传的文件大小超过了限制，请重新上传                                                               |
| 400           | invalid_request_error        | 文件大小为零，请确认并重新上传文件                                                                   | 上传的文件大小为 0，请重新上传                                                                     |
| 400           | invalid_request_error        | 您上传的文件数量超过最大文件数 {max_file_count}，请删除之前上传的文件                                | 上传的文件总数超限，请删除不用的早期的文件后重新上传                                               |
| 401           | invalid_authentication_error | 无效身份验证                                                                                         | 鉴权失败，请检查 apikey 是否正确，请修改后重试                                                     |
| 401           | invalid_authentication_error | 提供的 API 密钥不正确                                                                                | 鉴权失败，请检查 apikey 是否提供以及 apikey 是否正确，请修改后重试                                 |
| 429           | exceeded_current_quota_error | 您的帐户 {organization-id}<{ak-id}> 已暂停，请检查您的计划和账单详细信息                             | 账户余额不足，已停用，请检查您的账户余额                                                           |
| 403           | permission_denied_error      | 您正在访问的 API 未打开                                                                              | 访问的 API 暂未开放                                                                                |
| 403           | permission_denied_error      | 您不得获取其他用户信息                                                                               | 访问其他用户信息的行为不被允许，请检查                                                             |
| 404           | resource_not_found_error     | 未找到模型或权限被拒绝                                                                               | 不存在此模型或者没有授权访问此模型，请检查后重试                                                   |
| 429           | engine_overloaded_error      | 引擎当前过载，请稍后重试                                                                             | 当前并发请求过多，节点限流中，请稍后重试;建议充值升级 tier，享受更丝滑的体验                       |
| 429           | exceeded_current_quota_error | 您超出了当前代币额度：<{organization_id}>{token_credit}，请检查您的账户余额                          | 账户额度不足，请检查账户余额，保证账户余额可匹配您 tokens 的消耗费用后重试                         |
| 429           | rate_limit_reached_error     | 您的帐户 {organization-id}<{ak-id}>请求已达到组织最大并发数：{Concurrency}，请在 {time} 秒后重试     | 请求触发了账户并发个数的限制，请等待指定时间后重试                                                 |
| 429           | rate_limit_reached_error     | 您的帐户 {organization-id}<{ak-id}>请求已达到组织最大 RPM：{RPM}，请在 {time} 秒后重试               | 请求触发了账户 RPM 速率限制，请等待指定时间后重试                                                  |
| 429           | rate_limit_reached_error     | 帐户 {organization-id}<{ak-id}>请求已达到组织 TPM 速率限制，当前：{current_tpm}，限制：{max_tpm}     | 请求触发了账户 TPM 速率限制，请等待指定时间后重试                                                  |
| 429           | rate_limit_reached_error     | 您的帐户 {organization-id}<{ak-id}>请求已达到组织 TPD 速率限制，当前：{current_tpd}，限制：{max_tpd} | 请求触发了账户 TPD 速率限制，请等待指定时间后重试                                                  |
| 500           | server_error                 | 无法提取文件：{error}                                                                                | 解析文件失败，请重试                                                                               |
| 500           | unexpected_output            | 无效状态转换                                                                                         | 内部错误，请联系管理员                                                                             |


# API 错误代码参考
{
    "error": {
        "type": "content_filter",
        "message": "The request was rejected because it was considered high risk"
    }
}