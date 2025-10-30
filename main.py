import argparse
import json
import os
import subprocess
import re
import sys
from typing import List, Dict, Any, Tuple

import requests


def _normalize_url(url: str) -> str:
	"""Ensure scheme for bare short links like b23.tv/xxxx."""
	s = url.strip()
	if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
		return s
	# If looks like a domain/path (e.g., b23.tv/abc), default to https
	if re.match(r"^(b23\.tv|acg\.tv|bili2233\.cn|bili2233\.com|bili\.(?:tv|com))/", s, re.IGNORECASE):
		return "https://" + s
	return s


def parse_input_to_bvid(user_input: str) -> str:
	"""Extract BV id from URL (incl. short links) or return as-is if already BV.*"""
	# 1) direct BV in input
	bv_match = re.search(r"BV[0-9A-Za-z]+", user_input)
	if bv_match:
		return bv_match.group(0)

	candidate = user_input.strip()

	# 2) try resolve common short links by following redirects
	short_domains = ("b23.tv", "acg.tv", "bili2233.cn", "bili2233.com")
	try:
		if any(d in candidate for d in short_domains):
			url = _normalize_url(candidate)
			resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, allow_redirects=True)
			final_url = resp.url or url
			bv_match2 = re.search(r"BV[0-9A-Za-z]+", final_url)
			if bv_match2:
				return bv_match2.group(0)
	except Exception:
		pass

	# 3) last attempt: if input is a long url without BV, still return stripped input
	return candidate


def get_view_info_by_bvid(bvid: str) -> Dict[str, Any]:
	"""Call web view API to get aid and cid (first page)."""
	resp = requests.get(
		"https://api.bilibili.com/x/web-interface/view",
		params={"bvid": bvid},
		headers={
			"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64)"},
		timeout=15,
	)
	resp.raise_for_status()
	data = resp.json()
	if data.get("code") != 0:
		raise RuntimeError(f"view api error: {data.get('code')} {data.get('message')}")
	return data["data"]


def get_subtitle_list_web(aid: int, cid: int) -> List[Dict[str, Any]]:
	"""
	Try web player API for subtitle list (unauthenticated, non-intl).
	Returns a list of items with at least fields: lan, url.
	"""
	resp = requests.get(
		"https://api.bilibili.com/x/player/wbi/v2",
		params={"aid": aid, "cid": cid},
		headers={
			"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64)",
			"Referer": "https://www.bilibili.com/",
		},
		timeout=15,
	)
	resp.raise_for_status()
	data = resp.json()
	if data.get("code") != 0:
		raise RuntimeError(f"player api error: {data.get('code')} {data.get('message')}")
	sub = data.get("data", {}).get("subtitle", {})
	items = sub.get("subtitles") or []
	# normalize fields: use 'url' if present, fallback to 'subtitle_url'
	result = []
	for it in items:
		url = it.get("url") or it.get("subtitle_url")
		lan = it.get("lan") or it.get("lang_key") or ""
		if url:
			result.append({"lan": lan, "url": url})
	return result


def get_subtitle_list_player_v2(aid: int, cid: int) -> List[Dict[str, Any]]:
	"""
	Alternative public player API which may expose AI subtitles.
	GET https://api.bilibili.com/x/player/v2?aid=..&cid=..
	"""
	resp = requests.get(
		"https://api.bilibili.com/x/player/v2",
		params={"aid": aid, "cid": cid},
		headers={
			"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64)",
			"Referer": "https://www.bilibili.com/",
		},
		timeout=15,
	)
	resp.raise_for_status()
	data = resp.json()
	if data.get("code") != 0:
		return []
	sub = (data.get("data") or {}).get("subtitle") or {}
	items = sub.get("subtitles") or []
	result = []
	for it in items:
		url = it.get("url") or it.get("subtitle_url")
		lan = it.get("lan") or it.get("lang_key") or ""
		if url:
			result.append({"lan": lan, "url": url})
	return result


def get_subtitle_list_from_html(bvid: str) -> List[Dict[str, Any]]:
    """(Deprecated in simplified flow) HTML scraping fallback was removed."""
    return []


def get_subtitle_list_app_dmview_json(cid: int) -> List[Dict[str, Any]]:
	"""
	APP DMView JSON endpoint (no login):
	GET https://api.bilibili.com/x/v2/dm/view?type=1&oid=<cid>
	Often contains AI subtitles under data.subtitle.subtitles[].
	"""
	resp = requests.get(
		"https://api.bilibili.com/x/v2/dm/view",
		params={"type": 1, "oid": cid},
		headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64)"},
		timeout=15,
	)
	resp.raise_for_status()
	data = resp.json()
	if data.get("code") != 0:
		return []
	subs = (((data.get("data") or {}).get("subtitle") or {}).get("subtitles") or [])
	result = []
	for it in subs:
		url = it.get("subtitle_url") or it.get("url")
		lan = it.get("lan") or it.get("lang_key") or ""
		if url:
			result.append({"lan": lan, "url": url})
	return result


def categorize_language(lan_key: str) -> str:
    l = (lan_key or "").lower()
    if l.startswith("ai-en") or l == "en" or l.startswith("en-"):
        return "en"
    if l.startswith("ai-zh") or l == "zh" or l.startswith("zh-"):
        return "zh"
    return "other"


def select_by_priority(subs: List[Dict[str, Any]], priority: List[str]) -> Tuple[List[Dict[str, Any]], str]:
    buckets: Dict[str, List[Dict[str, Any]]] = {"en": [], "zh": [], "other": []}
    for it in subs:
        buckets[categorize_language(it.get("lan", ""))].append(it)
    for p in priority:
        if buckets.get(p):
            return buckets[p], p
    return [], ""


def json_subtitle_to_srt(body: List[Dict[str, Any]]) -> str:
	"""Convert bilibili subtitle JSON body to SRT text."""
	def fmt_time(t: float) -> str:
		ms = int(round((t - int(t)) * 1000))
		sec = int(t) % 60
		minutes = (int(t) // 60) % 60
		hours = int(t) // 3600
		return f"{hours:02d}:{minutes:02d}:{sec:02d},{ms:03d}"

	lines = []
	index = 1
	for item in body:
		start = float(item.get("from", 0.0))
		end = float(item.get("to", 0.0))
		content = (item.get("content") or "").strip()
		if not content:
			continue
		lines.append(str(index))
		lines.append(f"{fmt_time(start)} --> {fmt_time(end)}")
		lines.append(content)
		lines.append("")
		index += 1
	return "\n".join(lines)


def subtitle_json_to_plaintext(body: List[Dict[str, Any]]) -> str:
	"""Flatten subtitle JSON body into plain text for summarization."""
	parts: List[str] = []
	for item in body:
		content = (item.get("content") or "").strip()
		if content:
			parts.append(content)
	return "\n".join(parts)


def download_subtitle_srt(url: str) -> str:
    """Fetch subtitle JSON and return SRT text."""
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    body = data.get("body") or []
    return json_subtitle_to_srt(body)


def download_subtitle_plaintext(url: str) -> str:
	"""Fetch subtitle JSON and return flattened plain text."""
	resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
	resp.raise_for_status()
	data = resp.json()
	body = data.get("body") or []
	return subtitle_json_to_plaintext(body)


def copy_to_clipboard(text: str) -> None:
    """Copy given text to Windows clipboard using 'clip'."""
    try:
        # Use shell=True to locate built-in 'clip' command on Windows
        subprocess.run("clip", input=text, text=True, check=True, shell=True)
    except Exception as e:
        raise RuntimeError(f"复制到剪贴板失败: {e}")


def fetch_bilibili_subtitle_text(video_url: str, whitelist: list = None, lang_priority: list = None) -> dict:
    """
    对外统一API接口：输入视频号/链接，返回 {'text': ..., 'lang': ...}。
    whitelist: （可选）语言码白名单
    lang_priority: 优先级
    """
    try:
        bvid = parse_input_to_bvid(video_url)
        view = get_view_info_by_bvid(bvid)
        aid = int(view["aid"])
        cid = int(view["cid"])
        subs = get_subtitle_list_web(aid, cid)
        if not subs:
            subs = get_subtitle_list_player_v2(aid, cid)
        if not subs:
            subs = get_subtitle_list_app_dmview_json(cid)
        if not subs:
            return {"code": 1, "msg": "未发现可用字幕（未登录或仅AI且接口不返回）", "text": "", "lang": ""}
        selected = []
        if whitelist:
            for it in subs:
                lan = it["lan"] or ""
                if any(lan == w or (lan.startswith(w) and w.endswith("-")) for w in whitelist):
                    selected.append(it)
            if not selected:
                return {"code": 2, "msg": "按白名单过滤后无可用字幕。", "text": "", "lang": ""}
        if not selected:
            prio = lang_priority or ["en", "zh", "other"]
            selected, picked = select_by_priority(subs, prio)
            if not selected:
                return {"code": 3, "msg": "按优先级选择后无可用字幕。", "text": "", "lang": ""}
        pick = selected[0]
        text = download_subtitle_plaintext(pick["url"])
        return {"code": 0, "msg": "ok", "text": text, "lang": pick.get('lan') or ''}
    except Exception as e:
        return {"code": 99, "msg": f"处理异常: {e}", "text": "", "lang": ""}


def main() -> int:
	parser = argparse.ArgumentParser(description="Minimal Bilibili subtitle fetcher (unauth, non-intl)")
	parser.add_argument("--input", required=True, help="BV号或视频URL")
	parser.add_argument("--outdir", default=".", help="输出目录")
	parser.add_argument("--allow-ai", action="store_true", help="(兼容保留) 可忽略")
	parser.add_argument("--lang", default="", help="(可选) 逗号分隔的语言键白名单，提供则覆盖优先级逻辑")
	parser.add_argument("--lang-priority", default="en,zh,other", help="字幕语言优先级，默认 en,zh,other，仅下载首个可用类别")
	parser.add_argument("--subtitle-url", default="", help="直接提供字幕JSON地址(适用于AI字幕调试)")
	parser.add_argument("--lan-key", default="und", help="与 --subtitle-url 搭配，指定保存文件的语言键")
	args = parser.parse_args()

	try:
		# Direct URL mode (e.g., AI subtitle JSON URL)
		if args.subtitle_url:
			bvid = parse_input_to_bvid(args.input)
			text = download_subtitle_plaintext(args.subtitle_url)
			copy_to_clipboard(text)
			print("字幕已复制到剪贴板")
			return 0

		bvid = parse_input_to_bvid(args.input)
		view = get_view_info_by_bvid(bvid)
		aid = int(view["aid"])
		cid = int(view["cid"])  # first page
		subs = get_subtitle_list_web(aid, cid)
		if not subs:
			# try alternative player v2 (may include AI)
			subs = get_subtitle_list_player_v2(aid, cid)
		if not subs:
			# try APP DMView JSON (often returns AI subtitles)
			subs = get_subtitle_list_app_dmview_json(cid)
		# HTML fallback removed in simplified flow
		if not subs:
			print("未发现可用字幕（未登录或仅AI且接口不返回）。")
			return 0

		# 1) 若提供 --lang，则按白名单过滤（保留原有能力）
		whitelist = [s.strip() for s in args.lang.split(",") if s.strip()]
		selected = []
		for it in subs:
			lan = it["lan"] or ""
			if not whitelist:
				continue
			if any(lan == w or (lan.startswith(w) and w.endswith("-")) for w in whitelist):
				selected.append(it)

		# 若提供了白名单但没有匹配结果，直接提示退出，避免后续索引错误
		if whitelist and not selected:
			print("按白名单过滤后无可用字幕。")
			return 0

		# 2) 未给 --lang 时，走优先级逻辑：仅下载优先级最高的语言类别
		if not whitelist:
			priority = [p.strip() for p in args.lang_priority.split(',') if p.strip()]
			selected, picked = select_by_priority(subs, priority)
			if not selected:
				print("按优先级选择后无可用字幕。")
				return 0

		# 仅复制一个优先字幕到剪贴板：
		try:
			pick = selected[0]
			text = download_subtitle_plaintext(pick["url"])
			copy_to_clipboard(text)
			print(f"字幕已复制到剪贴板（语言: {pick.get('lan') or 'und'}）")
			return 0
		except Exception as e:
			print(f"处理失败: {e}")
			return 1
	except Exception as e:
		print(f"错误: {e}")
		return 1


if __name__ == "__main__":
	sys.exit(main())


