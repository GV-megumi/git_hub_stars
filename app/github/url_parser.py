from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.errors import ValidationError

_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_ASCII_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_github_repo_url(raw_url: str) -> RepoRef:
    if not isinstance(raw_url, str):
        raise ValidationError("请输入 https://github.com/{owner}/{repo} 格式的仓库地址。")
    if _ASCII_CONTROL_PATTERN.search(raw_url):
        raise ValidationError("仓库地址不能包含控制字符。")

    url = raw_url.strip()
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValidationError("请输入有效的 Github 仓库地址。") from exc

    if parsed.scheme != "https":
        raise ValidationError("请输入 https://github.com/{owner}/{repo} 格式的仓库地址。")
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValidationError("只支持 github.com 仓库地址。")
    if parsed.params or parsed.query or parsed.fragment or ";" in url or "?" in url or "#" in url:
        raise ValidationError("请输入仓库根地址，不要包含路径参数、查询参数、锚点或其他子路径。")

    parts = parsed.path.split("/")
    if len(parts) == 4 and parts[-1] == "":
        parts = parts[:-1]
    if len(parts) != 3 or parts[0] != "":
        raise ValidationError("请输入仓库根地址，不要包含 issues、pulls 或其他子路径。")

    owner, repo = parts[1:]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValidationError("仓库地址缺少 owner 或 repo。")
    if owner in {".", ".."} or repo in {".", ".."}:
        raise ValidationError("仓库 owner 或 repo 名称格式不正确。")
    if not _OWNER_PATTERN.fullmatch(owner) or not _REPO_PATTERN.fullmatch(repo):
        raise ValidationError("仓库 owner 或 repo 名称格式不正确。")

    return RepoRef(owner=owner, repo=repo)
