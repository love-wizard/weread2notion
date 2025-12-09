import argparse
import json
import logging
import os
import re
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
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {}
    cookiejar = None
    for key, morsel in cookie.items():
        cookies_dict[key] = morsel.value
        cookiejar = cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)
    return cookiejar

def refresh_token(exception):
    session.get(WEREAD_URL)
    return True

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_bookmark_list(bookId):
    """获取我的划线"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    r = session.get(WEREAD_BOOKMARKLIST_URL, params=params)
    if r.ok:
        data = r.json()
        # 检查是否有错误码
        if data.get("errCode") != 0 and "errCode" in data:
            raise Exception(data.get('errMsg', '登录超时'))
        updated = data.get("updated")
        if updated is None or not isinstance(updated, list):
            return []
        updated = sorted(
            updated,
            key=lambda x: (x.get("chapterUid", 1), int(x.get("range", "0-0").split("-")[0])),
        )
        return updated
    return []

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_read_info(bookId):
    session.get(WEREAD_URL)
    params = dict(bookId=bookId, readingDetail=1, readingBookIndex=1, finishedDate=1)
    r = session.get(WEREAD_READ_INFO_URL, params=params)
    if r.ok:
        data = r.json()
        if data.get("errCode") != 0 and "errCode" in data:
            raise Exception(data.get('errMsg', '登录超时'))
        return data
    return None

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_bookinfo(bookId):
    """获取书的详情"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId)
    r = session.get(WEREAD_BOOK_INFO, params=params)
    isbn = ""
    if r.ok:
        data = r.json()
        if data.get("errCode") != 0 and "errCode" in data:
            raise Exception(data.get('errMsg', '登录超时'))
        isbn = data.get("isbn","")
        newRating = data.get("newRating", 0) / 1000
        return (isbn, newRating)
    else:
        print(f"get {bookId} book info failed")
        return ("", 0)

@retry(stop_max_attempt_number=3, wait_fixed=5000,retry_on_exception=refresh_token)
def get_review_list(bookId):
    """获取笔记"""
    session.get(WEREAD_URL)
    params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
    r = session.get(WEREAD_REVIEW_LIST_URL, params=params)
    data = r.json()
    if data.get("errCode") != 0 and "errCode" in data:
        raise Exception(data.get('errMsg', '登录超时'))
    reviews = data.get("reviews")
    if not reviews:
        return [], []
    summary = list(filter(lambda x: x.get("review").get("type") == 4, reviews))
    reviews = list(filter(lambda x: x.get("review").get("type") == 1, reviews))
    reviews = list(map(lambda x: x.get("review"), reviews))
    reviews = list(map(lambda x: {**x, "markText": x.pop("content")}, reviews))
    return summary, reviews


def check(bookId):
    """检查是否已经插入过 如果已经插入了就删除"""
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
    r = session.post(WEREAD_CHAPTER_INFO, json=body)
    if r.ok:
        data = r.json()
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
    r = session.get(WEREAD_NOTEBOOKS_URL)
    if r.ok:
        data = r.json()
        books = data.get("books")
        books.sort(key=lambda x: x["sort"])
        return books
    else:
        print(r.text)
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
    if url and id and password:
        cookie = try_get_cloud_cookie(url, id, password)
    if not cookie or not cookie.strip():
        raise Exception("没有找到cookie，请按照文档填写cookie")
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
    parser = argparse.ArgumentParser()
    options = parser.parse_args()
    weread_cookie = get_cookie()
    notion_token = os.getenv("NOTION_TOKEN")
    if not notion_token or notion_token.strip() == "" or notion_token == "***":
        raise Exception("没有找到NOTION_TOKEN，请按照文档配置环境变量")
    session = requests.Session()
    session.cookies = parse_cookie_string(weread_cookie)
    client = Client(auth=notion_token, log_level=logging.ERROR)
    
    # database_id 用于创建页面，data_source_id 用于查询
    database_id = extract_page_id()
    data_source_id = get_data_source_id(database_id)
    
    session.get(WEREAD_URL)
    latest_sort = get_sort()
    books = get_notebooklist()
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    if books != None:
        print(f"\n开始同步，共 {len(books)} 本书籍，最新排序值: {latest_sort}\n")
        for index, book in enumerate(books):
            sort = book["sort"]
            if sort <= latest_sort:
                skip_count += 1
                continue
            book = book.get("book")
            title = book.get("title")
            cover = book.get("cover").replace("/s_", "/t7_")
            bookId = book.get("bookId")
            author = book.get("author")
            categories = book.get("categories")
            if categories != None:
                categories = [x["title"] for x in categories]
            print(f"[{index+1}/{len(books)}] 正在同步《{title}》...")
            
            try:
                check(bookId)
                isbn, rating = get_bookinfo(bookId)
                id = insert_to_notion(
                    title, bookId, cover, sort, author, isbn, rating, categories
                )
                chapter = get_chapter_info(bookId)
                bookmark_list = get_bookmark_list(bookId)
                summary, reviews = get_review_list(bookId)
                bookmark_list.extend(reviews)
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
                results = add_children(id, children)
                if len(grandchild) > 0 and results != None:
                    add_grandchild(grandchild, results)
                print(f"  ✓ 成功")
                success_count += 1
            except Exception as e:
                print(f"  ✗ 失败: {e}")
                fail_count += 1
                continue
        
        print(f"\n同步完成！")
        print(f"  成功: {success_count} 本")
        print(f"  失败: {fail_count} 本")
        print(f"  跳过: {skip_count} 本")
