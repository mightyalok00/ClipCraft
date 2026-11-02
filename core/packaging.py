"""Multi-Platform SEO, Metadata, and Viral Packaging Generator."""
from __future__ import annotations

from typing import Any


def package_clip(
    highlight: dict[str, Any],
    content_type: str = "general",
) -> dict[str, Any]:
    """Generate platform-specific titles, captions, and hashtags."""
    title = highlight.get("title", "Must Watch")
    hook = highlight.get("hook_sentence") or highlight.get("hook") or highlight.get("first_line") or title
    reason = highlight.get("virality_reason", "")

    # Base tags by content category
    category_tags = {
        "gaming": ["#gaming", "#gamer", "#gamingshorts", "#twitch", "#fyp"],
        "podcast": ["#podcast", "#podcasting", "#deepthoughts", "#mindset", "#fyp"],
        "educational": ["#education", "#techtips", "#learnontiktok", "#productivity", "#lifehacks", "#fyp"],
        "education": ["#education", "#techtips", "#learnontiktok", "#productivity", "#lifehacks", "#fyp"],
        "vlog": ["#vlog", "#storytime", "#relatable", "#funny", "#fyp"],
        "general": ["#viral", "#shorts", "#trending", "#reels", "#fyp"],
    }
    tags = category_tags.get(content_type.lower(), category_tags["general"])

    # YouTube Shorts title (keep punchy, under 60 chars)
    yt_title = title if len(title) <= 55 else title[:52] + "..."
    yt_description = (
        f"{hook}\n\n"
        f"{reason}\n\n"
        f"Subscribe for more daily shorts!\n\n"
        f"{' '.join(tags[:3])}"
    )

    # Instagram Reels: First 125 chars MUST deliver the hook before the "... more" truncation
    reels_hook = hook if len(hook) <= 120 else hook[:117] + "..."
    reels_caption = (
        f"{reels_hook}\n\n"
        f"Drop your thoughts below 👇\n\n"
        f"{' '.join(tags)}"
    )

    # TikTok Caption: Keywords focused
    tiktok_caption = f"{yt_title} 🤯 {' '.join(tags)}"

    return {
        "youtube_title": yt_title,
        "youtube_description": yt_description,
        "reels_caption": reels_caption,
        "tiktok_caption": tiktok_caption,
        "hashtags": tags,
    }


def package_clip_deliverables(clip: dict[str, Any]) -> dict[str, Any]:
    """Convenience packager creating standardized schema for deliverable bundles."""
    content_type = clip.get("category", "general")
    pkg = package_clip(clip, content_type=content_type)
    return {
        "virality_score": clip.get("virality_score", 0),
        "youtube": {
            "title": f"{pkg['youtube_title']} #Shorts",
            "description": pkg["youtube_description"],
            "hashtags": pkg["hashtags"],
        },
        "reels": {
            "caption": pkg["reels_caption"],
            "hashtags": pkg["hashtags"],
        },
        "tiktok": {
            "caption": pkg["tiktok_caption"],
            "hashtags": pkg["hashtags"],
        },
    }

