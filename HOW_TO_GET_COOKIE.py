#!/usr/bin/env python3
"""
帮助从浏览器获取微信读书Cookie的指南

请按照以下步骤操作：

1. 打开浏览器，访问 https://weread.qq.com/
2. 确保已登录
3. 打开开发者工具（F12）
4. 点击顶部的 "Network" (网络) 标签
5. 刷新页面
6. 在请求列表中找到任意一个请求（比如notebook）
7. 点击该请求，在右侧找到 "Headers" (请求头)
8. 向下滚动找到 "Request Headers" (请求头)
9. 找到 "cookie:" 这一行
10. 复制完整的Cookie字符串

Cookie应该包含以下关键字段：
- wr_skey (最重要！必须是最新的)
- wr_vid
- wr_gid  
- wr_rt

示例格式：
RK=xxx; wr_skey=xxx; wr_vid=xxx; wr_gid=xxx; ...

---

或者，使用更简单的方法：

在浏览器控制台（Console）中运行以下代码：

document.cookie

这会输出当前页面的所有Cookie，复制整个字符串即可。

---

⚠️ 重要提示：
- wr_skey 是动态会话密钥，会定期过期
- 建议使用 CookieCloud 进行自动同步，避免频繁手动更新
- Cookie 包含敏感信息，请妥善保管

---

如果你想使用 CookieCloud 自动同步（推荐）：

1. 安装 CookieCloud 浏览器扩展
2. 配置同步服务器和密码
3. 在 .env 文件中配置：
   CC_URL=你的CookieCloud服务器地址
   CC_ID=你的ID  
   CC_PASSWORD=你的密码

这样脚本会自动获取最新的Cookie，无需手动更新。
"""

print(__doc__)
