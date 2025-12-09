#!/usr/bin/env python3
"""测试微信读书API接口"""

import requests
from http.cookies import SimpleCookie
from requests.utils import cookiejar_from_dict
import os
from dotenv import load_dotenv
import json

load_dotenv()

def parse_cookie_string(cookie_string):
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    for key, morsel in cookie.items():
        cookies_dict[key] = morsel.value
    cookiejar = cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)
    return cookiejar

# 获取Cookie
cookie_str = os.getenv("WEREAD_COOKIE")
print(f"Cookie长度: {len(cookie_str)}")
print(f"Cookie前50字符: {cookie_str[:50]}...\n")

# 创建session
session = requests.Session()
session.cookies = parse_cookie_string(cookie_str)

# 设置请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://weread.qq.com/',
    'Origin': 'https://weread.qq.com',
}

# 测试1: 访问主页
print("=" * 60)
print("测试 1: 访问主页")
print("=" * 60)
response = session.get("https://weread.qq.com/", headers=headers)
print(f"状态码: {response.status_code}")
print(f"响应头: {dict(response.headers)}")
print(f"Cookie数量: {len(session.cookies)}")
print(f"Cookie列表: {[c.name for c in session.cookies]}\n")

# 测试2: 获取笔记本列表
print("=" * 60)
print("测试 2: 获取笔记本列表")
print("=" * 60)
url = "https://weread.qq.com/api/user/notebook"
response = session.get(url, headers=headers)
print(f"请求URL: {url}")
print(f"状态码: {response.status_code}")
print(f"响应头: {dict(response.headers)}")
data = response.json()
print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)[:500]}...\n")
if "books" in data and len(data["books"]) > 0:
    test_book_id = data["books"][0]["book"]["bookId"]
    print(f"测试书籍ID: {test_book_id}\n")
else:
    print("没有找到书籍，退出")
    exit(1)

# 测试3: 获取书籍详情
print("=" * 60)
print("测试 3: 获取书籍详情 (get_bookinfo)")
print("=" * 60)
url = "https://weread.qq.com/web/book/info"
params = {"bookId": test_book_id}
response = session.get(url, params=params, headers=headers)
print(f"请求URL: {response.url}")
print(f"状态码: {response.status_code}")
print(f"请求头: {json.dumps(dict(response.request.headers), ensure_ascii=False, indent=2)}")
print(f"响应头: {json.dumps(dict(response.headers), ensure_ascii=False, indent=2)}")
data = response.json()
print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}\n")

# 测试4: 获取阅读信息
print("=" * 60)
print("测试 4: 获取阅读信息 (get_read_info)")
print("=" * 60)
url = "https://weread.qq.com/web/book/readinfo"
params = {"bookId": test_book_id, "readingDetail": 1, "readingBookIndex": 1, "finishedDate": 1}
response = session.get(url, params=params, headers=headers)
print(f"请求URL: {response.url}")
print(f"状态码: {response.status_code}")
print(f"请求头: {json.dumps(dict(response.request.headers), ensure_ascii=False, indent=2)}")
print(f"响应头: {json.dumps(dict(response.headers), ensure_ascii=False, indent=2)}")
data = response.json()
print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}\n")

# 测试5: 获取划线列表
print("=" * 60)
print("测试 5: 获取划线列表 (get_bookmark_list)")
print("=" * 60)
url = "https://weread.qq.com/web/book/bookmarklist"
params = {"bookId": test_book_id}
response = session.get(url, params=params, headers=headers)
print(f"请求URL: {response.url}")
print(f"状态码: {response.status_code}")
print(f"请求头: {json.dumps(dict(response.request.headers), ensure_ascii=False, indent=2)}")
print(f"响应头: {json.dumps(dict(response.headers), ensure_ascii=False, indent=2)}")
data = response.json()
print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}\n")

# 显示当前session中的所有cookie
print("=" * 60)
print("当前 Session Cookie 详情")
print("=" * 60)
for cookie in session.cookies:
    print(f"名称: {cookie.name}")
    print(f"  值: {cookie.value[:30]}..." if len(cookie.value) > 30 else f"  值: {cookie.value}")
    print(f"  域: {cookie.domain}")
    print(f"  路径: {cookie.path}")
    print(f"  过期: {cookie.expires}")
    print()
