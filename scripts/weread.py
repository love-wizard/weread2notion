import argparse
import json
import logging
import os
import re
import sys
import time
from notion_client import Client
import requests
from requests.utils import cookiejar_from_dict
from http.cookies import SimpleCookie
from datetime import datetime
import hashlib
from dotenv import load_dotenv
import os
from retrying import retry

# 强制刷新输出，确保在GitHub Actions中能看到实时日志
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
from utils import (
    get_callout,
    get_date,
    get_file,
    get_heading,
    get_icon,
    get_multi_select,
    get_number,
    get_quote,
    get_rich_text,
    get_select,
    get_table_of_contents,
    get_title,
    get_url,
)
load_dotenv()
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"

# 全局变量
database_id = None  # 数据库ID，用于创建页面
data_source_id = None  # 数据源ID，用于查询


def parse_cookie_string(cookie_string):
    """解析Cookie字符串并返回cookiejar
    注意：这里只解析初始Cookie，服务器动态设置的Cookie（如wr_skey）会自动更新
    """
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    for key, morsel in cookie.items():
        cookies_dict[key] = morsel.value
    
    # 使用cookiejar_from_dict创建cookiejar，这样可以让requests自动管理Cookie更新
    cookiejar = cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)
    
    if not cookies_dict:
        print(f"⚠️  警告: Cookie 解析后为空！")
        print(f"原始 Cookie: {cookie_string[:100]}...")
        sys.stdout.flush()
    else:
        print(f"✓ Cookie 解析成功，包含 {len(cookies_dict)} 个字段")
        print(f"Cookie 字段: {list(cookies_dict.keys())}")
        sys.stdout.flush()
    
    return cookiejar

def refresh_token(exception):
    session.get(WEREAD_URL)
    return True

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_bookmark_list(bookId):
    """获取我的划线"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://weread.qq.com/',
        'Origin': 'https://weread.qq.com',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin'
    }
    r = session.get(WEREAD_BOOKMARKLIST_URL, params=params, headers=headers)
    if r.ok:
        data = r.json()
        # 检查是否有错误码
        if data.get("errCode") != 0 and "errCode" in data:
            # 打印详细的错误信息用于调试
            if data.get("errCode") == -2012:
                print(f"  调试: bookmarklist API失败")
                print(f"  请求URL: {r.url}")
                print(f"  响应: {data}")
                cookie_names = [c.name for c in session.cookies]
                print(f"  Cookie字段: {cookie_names}")
                sys.stdout.flush()
            raise Exception(data.get('errMsg', '登录超时'))
        updated = data.get("updated")
        
        # 添加调试信息
        if updated is None:
            print(f"  [DEBUG] bookmarklist API返回updated=None, bookId={bookId}")
            print(f"  [DEBUG] 完整响应: {data}")
            sys.stdout.flush()
        elif not isinstance(updated, list):
            print(f"  [DEBUG] bookmarklist API返回updated类型错误: {type(updated)}, bookId={bookId}")
            sys.stdout.flush()
        elif len(updated) == 0:
            print(f"  [DEBUG] bookmarklist API返回空列表, bookId={bookId}")
            print(f"  [DEBUG] 响应keys: {list(data.keys())}")
            sys.stdout.flush()
        
        if updated is None or not isinstance(updated, list):
            return []
        updated = sorted(
            updated,
            key=lambda x: (x.get("chapterUid", 1), int(x.get("range", "0-0").split("-")[0])),
        )
        return updated
    return []

def get_read_info(bookId):
    """获取阅读信息 - 如果失败返回None而不中断流程"""
    try:
        session.get(WEREAD_URL)
        params = dict(bookId=bookId, readingDetail=1, readingBookIndex=1, finishedDate=1)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://weread.qq.com/',
        }
        r = session.get(WEREAD_READ_INFO_URL, params=params, headers=headers)
        if r.ok:
            data = r.json()
            # 如果返回登录超时错误（-2012），返回None
            if data.get("errCode") == -2012:
                return None
            if data.get("errCode") != 0 and "errCode" in data:
                print(f"  [DEBUG] get_read_info 其他错误: errCode={data.get('errCode')}, errMsg={data.get('errMsg')}")
                sys.stdout.flush()
                return None
            return data
        return None
    except Exception as e:
        print(f"  [提示] 获取阅读信息异常: {e}")
        sys.stdout.flush()
        return None

def get_bookinfo(bookId):
    """获取书的详情"""
    try:
        session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://weread.qq.com/',
        }
        r = session.get(WEREAD_BOOK_INFO, params=params, headers=headers)
        isbn = ""
        if r.ok:
            data = r.json()
            # 如果返回登录超时错误（-2012），返回默认值而不是抛出异常
            if data.get("errCode") == -2012:
                print(f"  [提示] 获取书籍详情失败（权限不足），使用默认值")
                sys.stdout.flush()
                return ("", 0)
            if data.get("errCode") != 0 and "errCode" in data:
                print(f"  [DEBUG] get_bookinfo 其他错误: errCode={data.get('errCode')}, errMsg={data.get('errMsg')}")
                sys.stdout.flush()
                return ("", 0)
            isbn = data.get("isbn","")
            newRating = data.get("newRating", 0) / 1000
            return (isbn, newRating)
        else:
            print(f"  [提示] 获取书籍详情HTTP失败, status={r.status_code}")
            return ("", 0)
    except Exception as e:
        print(f"  [提示] 获取书籍详情异常: {e}")
        sys.stdout.flush()
        return ("", 0)

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_review_list(bookId):
    """获取笔记"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://weread.qq.com/',
    }
    r = session.get(WEREAD_REVIEW_LIST_URL, params=params, headers=headers)
    data = r.json()
    # 如果是登录超时，返回空数据而不是抛出异常
    if data.get("errCode") == -2012:
        print(f"  [DEBUG] review_list API登录超时, bookId={bookId}")
        sys.stdout.flush()
        return [], []
    if data.get("errCode") != 0 and "errCode" in data:
        raise Exception(data.get('errMsg', '登录超时'))
    reviews = data.get("reviews")
    if not reviews:
        print(f"  [DEBUG] review_list API返回空reviews, bookId={bookId}")
        print(f"  [DEBUG] 响应keys: {list(data.keys())}")
        sys.stdout.flush()
        return [], []
    summary = list(filter(lambda x: x.get("review").get("type") == 4, reviews))
    reviews = list(filter(lambda x: x.get("review").get("type") == 1, reviews))
    reviews = list(map(lambda x: x.get("review"), reviews))
    reviews = list(map(lambda x: {**x, "markText": x.pop("content")}, reviews))
    return summary, reviews


def check_exists(bookId):
    """检查书籍是否已存在，不删除"""
    filter = {"property": "BookId", "rich_text": {"equals": bookId}}
    response = client.request(
        path=f"data_sources/{data_source_id}/query",
        method="POST",
        body={"filter": filter}
    )
    return len(response["results"]) > 0

def delete_book(bookId):
    """删除已存在的书籍"""
    filter = {"property": "BookId", "rich_text": {"equals": bookId}}
    response = client.request(
        path=f"data_sources/{data_source_id}/query",
        method="POST",
        body={"filter": filter}
    )
    for result in response["results"]:
        try:
            client.blocks.delete(block_id=result["id"])
        except Exception as e:
            print(f"删除块时出错: {e}")

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_chapter_info(bookId):
    """获取章节信息"""
    session.get(WEREAD_URL)
    body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/json',
        'Referer': 'https://weread.qq.com/',
    }
    r = session.post(WEREAD_CHAPTER_INFO, json=body, headers=headers)
    if r.ok:
        data = r.json()
        # 如果是登录超时，返回None
        if data.get("errCode") == -2012:
            return None
        if data.get("errCode") != 0 and "errCode" in data:
            raise Exception(data.get('errMsg', '登录超时'))
        if (
            "data" in data
            and len(data["data"]) == 1
            and "updated" in data["data"][0]
        ):
            update = data["data"][0]["updated"]
            return {item["chapterUid"]: item for item in update}
    return None


def insert_to_notion(bookName, bookId, cover, sort, author, isbn, rating, categories):
    """插入到notion"""
    if not cover or not cover.startswith("http"):
        cover = "https://www.notion.so/icons/book_gray.svg"
    parent = {"database_id": database_id, "type": "database_id"}
    properties = {
        "BookName": get_title(bookName),
        "BookId": get_rich_text(bookId),
        "ISBN": get_rich_text(isbn),
        "URL": get_url(
            f"https://weread.qq.com/web/reader/{calculate_book_str_id(bookId)}"
        ),
        "Author": get_rich_text(author),
        "Sort": get_number(sort),
        "Rating": get_number(rating),
        "Cover": get_file(cover),
    }
    if categories != None:
        properties["Categories"] = get_multi_select(categories)
    read_info = get_read_info(bookId=bookId)
    if read_info != None:
        markedStatus = read_info.get("markedStatus", 0)
        readingTime = read_info.get("readingTime", 0)
        readingProgress = read_info.get("readingProgress", 0)
        format_time = ""
        hour = readingTime // 3600
        if hour > 0:
            format_time += f"{hour}时"
        minutes = readingTime % 3600 // 60
        if minutes > 0:
            format_time += f"{minutes}分"
        properties["Status"] = get_select("读完" if markedStatus == 4 else "在读")
        properties["ReadingTime"] = get_rich_text(format_time)
        properties["Progress"] = get_number(readingProgress)
        if "finishedDate" in read_info:
            properties["Date"] = get_date(
                datetime.utcfromtimestamp(read_info.get("finishedDate")).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

    icon = get_icon(cover)
    # notion api 限制100个block
    response = client.pages.create(parent=parent, icon=icon,cover=icon, properties=properties)
    id = response["id"]
    return id


def add_children(id, children):
    if not children or len(children) == 0:
        return []
    results = []
    for i in range(0, len(children) // 100 + 1):
        batch = children[i * 100 : (i + 1) * 100]
        if not batch:  # 跳过空批次
            continue
        time.sleep(0.3)
        try:
            response = client.blocks.children.append(
                block_id=id, children=batch
            )
            results.extend(response.get("results"))
        except Exception as e:
            print(f"添加blocks失败: {e}")
            return None
    return results if len(results) == len(children) else None


def add_grandchild(grandchild, results):
    for key, value in grandchild.items():
        time.sleep(0.3)
        id = results[key].get("id")
        client.blocks.children.append(block_id=id, children=[value])


def get_notebooklist():
    """获取笔记本列表"""
    session.get(WEREAD_URL)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://weread.qq.com/',
    }
    r = session.get(WEREAD_NOTEBOOKS_URL, headers=headers)
    if r.ok:
        data = r.json()
        # 检查是否有错误码
        if "errCode" in data and data.get("errCode") != 0:
            print(f"获取笔记本列表失败: {data}")
            sys.stdout.flush()
            return None
        books = data.get("books")
        if books:
            books.sort(key=lambda x: x["sort"])
            return books
        else:
            print("警告: 返回的书籍列表为空")
            sys.stdout.flush()
            return []
    else:
        print(f"请求失败，状态码: {r.status_code}")
        print(f"响应内容: {r.text[:500]}")
        sys.stdout.flush()
    return None


def get_sort():
    """获取database中的最新时间"""
    filter = {"property": "Sort", "number": {"is_not_empty": True}}
    sorts = [
        {
            "property": "Sort",
            "direction": "descending",
        }
    ]
    response = client.request(
        path=f"data_sources/{data_source_id}/query",
        method="POST",
        body={"filter": filter, "sorts": sorts, "page_size": 1}
    )
    if len(response.get("results")) == 1:
        return response.get("results")[0].get("properties").get("Sort").get("number")
    return 0


def get_children(chapter, summary, bookmark_list):
    children = []
    grandchild = {}
    if chapter != None:
        # 添加目录
        children.append(get_table_of_contents())
        d = {}
        for data in bookmark_list:
            chapterUid = data.get("chapterUid", 1)
            if chapterUid not in d:
                d[chapterUid] = []
            d[chapterUid].append(data)
        for key, value in d.items():
            if key in chapter:
                # 添加章节
                children.append(
                    get_heading(
                        chapter.get(key).get("level"), chapter.get(key).get("title")
                    )
                )
            for i in value:
                markText = i.get("markText")
                for j in range(0, len(markText) // 2000 + 1):
                    children.append(
                        get_callout(
                            markText[j * 2000 : (j + 1) * 2000],
                            i.get("style"),
                            i.get("colorStyle"),
                            i.get("reviewId"),
                        )
                    )
                if i.get("abstract") != None and i.get("abstract") != "":
                    quote = get_quote(i.get("abstract"))
                    grandchild[len(children) - 1] = quote

    else:
        # 如果没有章节信息
        for data in bookmark_list:
            markText = data.get("markText")
            for i in range(0, len(markText) // 2000 + 1):
                children.append(
                    get_callout(
                        markText[i * 2000 : (i + 1) * 2000],
                        data.get("style"),
                        data.get("colorStyle"),
                        data.get("reviewId"),
                    )
                )
    if summary != None and len(summary) > 0:
        children.append(get_heading(1, "点评"))
        for i in summary:
            content = i.get("review").get("content")
            for j in range(0, len(content) // 2000 + 1):
                children.append(
                    get_callout(
                        content[j * 2000 : (j + 1) * 2000],
                        i.get("style"),
                        i.get("colorStyle"),
                        i.get("review").get("reviewId"),
                    )
                )
    return children, grandchild


def transform_id(book_id):
    id_length = len(book_id)

    if re.match(r"^\d*$", book_id):
        ary = []
        for i in range(0, id_length, 9):
            ary.append(format(int(book_id[i : min(i + 9, id_length)]), "x"))
        return "3", ary

    result = ""
    for i in range(id_length):
        result += format(ord(book_id[i]), "x")
    return "4", [result]


def calculate_book_str_id(book_id):
    md5 = hashlib.md5()
    md5.update(book_id.encode("utf-8"))
    digest = md5.hexdigest()
    result = digest[0:3]
    code, transformed_ids = transform_id(book_id)
    result += code + "2" + digest[-2:]

    for i in range(len(transformed_ids)):
        hex_length_str = format(len(transformed_ids[i]), "x")
        if len(hex_length_str) == 1:
            hex_length_str = "0" + hex_length_str

        result += hex_length_str + transformed_ids[i]

        if i < len(transformed_ids) - 1:
            result += "g"

    if len(result) < 20:
        result += digest[0 : 20 - len(result)]

    md5 = hashlib.md5()
    md5.update(result.encode("utf-8"))
    result += md5.hexdigest()[0:3]
    return result


def try_get_cloud_cookie(url, id, password):
    if url.endswith("/"):
        url = url[:-1]
    req_url = f"{url}/get/{id}"
    data = {"password": password}
    result = None
    response = requests.post(req_url, data=data)
    if response.status_code == 200:
        data = response.json()
        cookie_data = data.get("cookie_data")
        if cookie_data and "weread.qq.com" in cookie_data:
            cookies = cookie_data["weread.qq.com"]
            cookie_str = "; ".join(
                [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
            )
            result = cookie_str
    return result


def get_cookie():
    url = os.getenv("CC_URL")
    if not url:
        url = "https://cookiecloud.malinkang.com/"
    id = os.getenv("CC_ID")
    password = os.getenv("CC_PASSWORD")
    cookie = os.getenv("WEREAD_COOKIE")
    
    # 尝试从 CookieCloud 获取
    if url and id and password:
        print("尝试从 CookieCloud 获取 Cookie...")
        sys.stdout.flush()
        cloud_cookie = try_get_cloud_cookie(url, id, password)
        if cloud_cookie:
            print("✓ 成功从 CookieCloud 获取 Cookie")
            sys.stdout.flush()
            cookie = cloud_cookie
        else:
            print("✗ CookieCloud 获取失败，使用环境变量中的 Cookie")
            sys.stdout.flush()
    
    if not cookie or not cookie.strip():
        raise Exception("没有找到cookie，请按照文档填写cookie")
    
    # 显示 Cookie 的前几个字符用于验证（不显示完整 Cookie）
    cookie_preview = cookie[:50] + "..." if len(cookie) > 50 else cookie
    print(f"Cookie 预览: {cookie_preview}")
    print(f"Cookie 长度: {len(cookie)} 字符")
    sys.stdout.flush()
    
    return cookie
    


def extract_page_id():
    url = os.getenv("NOTION_PAGE")
    if not url:
        url = os.getenv("NOTION_DATABASE_ID")
    if not url:
        raise Exception("没有找到NOTION_PAGE，请按照文档填写")
    # 正则表达式匹配 32 个字符的 Notion page_id
    match = re.search(
        r"([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})",
        url,
    )
    if match:
        return match.group(0)
    else:
        raise Exception(f"获取NotionID失败，请检查输入的Url是否正确")


def get_data_source_id(database_id):
    """从数据库ID获取数据源ID"""
    try:
        # 尝试获取数据库信息
        response = client.request(
            path=f"databases/{database_id}",
            method="GET"
        )
        # 如果数据库有data_sources，获取第一个
        if "data_sources" in response and len(response["data_sources"]) > 0:
            return response["data_sources"][0]["id"]
        # 否则直接使用database_id（向后兼容）
        return database_id
    except Exception as e:
        print(f"获取数据源ID失败，尝试直接使用database_id: {e}")
        return database_id




if __name__ == "__main__":
    print("=" * 50)
    print("开始运行 WeRead to Notion 同步程序")
    print("=" * 50)
    sys.stdout.flush()
    
    parser = argparse.ArgumentParser()
    options = parser.parse_args()
    
    print("正在获取配置...")
    sys.stdout.flush()
    weread_cookie = get_cookie()
    notion_token = os.getenv("NOTION_TOKEN")
    if not notion_token or notion_token.strip() == "" or notion_token == "***":
        raise Exception("没有找到NOTION_TOKEN，请按照文档配置环境变量")
    
    print("正在初始化客户端...")
    sys.stdout.flush()
    session = requests.Session()
    session.cookies = parse_cookie_string(weread_cookie)
    # 设置必要的请求头，模拟浏览器行为
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://weread.qq.com/',
        'Origin': 'https://weread.qq.com'
    })
    client = Client(auth=notion_token, log_level=logging.ERROR)
    
    print("正在获取数据库信息...")
    sys.stdout.flush()
    # database_id 用于创建页面，data_source_id 用于查询
    database_id = extract_page_id()
    data_source_id = get_data_source_id(database_id)
    
    print("正在验证微信读书 Cookie...")
    sys.stdout.flush()
    # 先访问主页，建立会话
    test_response = session.get(WEREAD_URL)
    print(f"主页访问状态: {test_response.status_code}")
    # 显示实际发送的Cookie
    cookie_dict = {cookie.name: cookie.value for cookie in session.cookies}
    print(f"当前Session中的Cookie字段: {list(cookie_dict.keys())}")
    
    # 检查关键Cookie是否存在
    critical_cookies = ['wr_skey', 'wr_vid']
    missing_cookies = [c for c in critical_cookies if c not in cookie_dict]
    if missing_cookies:
        print(f"⚠️  警告: 缺少关键Cookie字段: {missing_cookies}")
    sys.stdout.flush()
    
    # 测试获取笔记本列表
    print("正在获取书籍列表...")
    sys.stdout.flush()
    latest_sort = get_sort()
    books = get_notebooklist()
    
    # 测试第一本书的API调用
    if books and len(books) > 0:
        test_book_id = books[0].get("book", {}).get("bookId")
        if test_book_id:
            print(f"\n测试API调用（使用第一本书 bookId: {test_book_id}）...")
            sys.stdout.flush()
            try:
                print("  - 测试 get_bookinfo...")
                sys.stdout.flush()
                test_isbn, test_rating = get_bookinfo(test_book_id)
                print(f"    ✓ 成功 (ISBN: {test_isbn}, Rating: {test_rating})")
                sys.stdout.flush()
            except Exception as e:
                print(f"    ✗ 失败: {e}")
                sys.stdout.flush()
            
            try:
                print("  - 测试 get_read_info...")
                sys.stdout.flush()
                test_read_info = get_read_info(test_book_id)
                print(f"    ✓ 成功")
                sys.stdout.flush()
            except Exception as e:
                print(f"    ✗ 失败: {e}")
                sys.stdout.flush()
            
            try:
                print("  - 测试 get_bookmark_list...")
                sys.stdout.flush()
                test_bookmarks = get_bookmark_list(test_book_id)
                print(f"    ✓ 成功 (获取到 {len(test_bookmarks)} 条划线)")
                sys.stdout.flush()
            except Exception as e:
                print(f"    ✗ 失败: {e}")
                sys.stdout.flush()
            print()
    
    if books is None:
        print("\n❌ 无法获取书籍列表，请检查 Cookie 是否有效")
        print("提示: 请确保 Cookie 包含必要的认证信息")
        sys.stdout.flush()
        sys.exit(1)
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    if books != None:
        print(f"\n开始同步，共 {len(books)} 本书籍，最新排序值: {latest_sort}")
        print("注意: 部分API可能因权限限制无法获取数据（ISBN、评分、阅读状态等），这不影响划线同步\n")
        sys.stdout.flush()
        for index, book in enumerate(books):
            sort = book["sort"]
            book = book.get("book")
            title = book.get("title")
            cover = book.get("cover").replace("/s_", "/t7_")
            bookId = book.get("bookId")
            author = book.get("author")
            categories = book.get("categories")
            if categories != None:
                categories = [x["title"] for x in categories]
            
            # 快速跳过：如果Sort值小于等于latest_sort，大概率已存在，直接跳过
            # 只有Sort值大于latest_sort的新书才会同步
            if sort <= latest_sort:
                skip_count += 1
                continue
            
            print(f"[{index+1}/{len(books)}] 正在同步《{title}》...")
            sys.stdout.flush()
            
            try:
                # 删除已存在的书籍（如果有）
                delete_book(bookId)
                isbn, rating = get_bookinfo(bookId)
                id = insert_to_notion(
                    title, bookId, cover, sort, author, isbn, rating, categories
                )
                chapter = get_chapter_info(bookId)
                bookmark_list = get_bookmark_list(bookId)
                summary, reviews = get_review_list(bookId)
                
                # 添加详细调试信息
                print(f"  - 划线数: {len(bookmark_list)}, 笔记数: {len(reviews)}, 点评数: {len(summary)}")
                if len(bookmark_list) == 0 and len(reviews) > 0:
                    print(f"  ⚠️  警告: 有笔记但没有划线，这不正常！bookId={bookId}")
                sys.stdout.flush()
                
                bookmark_list.extend(reviews)
                
                # 添加调试信息
                print(f"  - 总计 {len(bookmark_list)} 条内容")
                sys.stdout.flush()
                
                bookmark_list = sorted(
                    bookmark_list,
                    key=lambda x: (
                        x.get("chapterUid", 1),
                        (
                            0
                            if (
                                x.get("range", "") == ""
                                or x.get("range").split("-")[0] == ""
                            )
                            else int(x.get("range").split("-")[0])
                        ),
                    ),
                )
                children, grandchild = get_children(chapter, summary, bookmark_list)
                print(f"  - 生成了 {len(children)} 个内容块")
                sys.stdout.flush()
                
                results = add_children(id, children)
                if results is None:
                    print(f"  ⚠️  添加内容块时出现问题")
                    sys.stdout.flush()
                elif len(grandchild) > 0 and results != None:
                    add_grandchild(grandchild, results)
                
                print(f"  ✓ 成功")
                sys.stdout.flush()
                success_count += 1
            except Exception as e:
                error_msg = str(e)
                print(f"  ✗ 失败: {error_msg}")
                sys.stdout.flush()
                fail_count += 1
                continue
        
        print(f"\n同步完成！")
        print(f"  成功: {success_count} 本")
        print(f"  失败: {fail_count} 本")
        print(f"  跳过: {skip_count} 本")
        sys.stdout.flush()
