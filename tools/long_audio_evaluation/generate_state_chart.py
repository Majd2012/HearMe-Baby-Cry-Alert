from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "final_report"

W, H = 1400, 820
NAVY = "#0D284D"
BLUE = "#2E74B5"
LIGHT_BLUE = "#EAF2FB"
LIGHT_GOLD = "#FFF7E6"
TEXT = "#1F2937"
MUTED = "#475569"
BORDER = "#AFC3D8"
WHITE = "#FFFFFF"
GRAY = "#EEF2F7"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


FONT_TITLE = font(34, True)
FONT_STATE = font(25, True)
FONT_STATE_SMALL = font(22, False)
FONT_LABEL = font(18, False)
FONT_LABEL_BOLD = font(19, True)
FONT_NOTE = font(18, False)


def rtl(text: str) -> str:
    """Visual fallback for Hebrew in Pillow builds without libraqm."""
    return text[::-1]


def text_center(draw: ImageDraw.ImageDraw, xy, lines, fonts, fill=TEXT, spacing=4):
    x, y = xy
    heights = []
    widths = []
    for line, fnt in zip(lines, fonts):
        box = draw.textbbox((0, 0), line, font=fnt)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
    total_h = sum(heights) + spacing * (len(lines) - 1)
    cy = y - total_h / 2
    for line, fnt, width, height in zip(lines, fonts, widths, heights):
        draw.text((x - width / 2, cy), line, font=fnt, fill=fill)
        cy += height + spacing


def arrow(draw: ImageDraw.ImageDraw, points, fill=NAVY, width=3):
    draw.line(points, fill=fill, width=width, joint="curve")
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 12
    left = (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45))
    right = (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45))
    draw.polygon([(x2, y2), left, right], fill=fill)


def rounded_node(draw, box, title, subtitle, fill=WHITE):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=22, fill=fill, outline=BORDER, width=3)
    text_center(draw, ((x1 + x2) / 2, (y1 + y2) / 2), [title, subtitle], [FONT_STATE, FONT_STATE_SMALL])


def label_box(draw, xy, lines, hebrew=False, width=250):
    x, y = xy
    converted = []
    for line in lines:
        converted.append(rtl(line) if hebrew else line)
    heights = [draw.textbbox((0, 0), t, font=FONT_LABEL)[3] for t in converted]
    h = max(40, sum(heights) + 24)
    box = (x - width / 2, y - h / 2, x + width / 2, y + h / 2)
    draw.rounded_rectangle(box, radius=12, fill=WHITE, outline="#D9E2EC", width=1)
    text_center(draw, (x, y), converted, [FONT_LABEL] * len(converted), fill=MUTED, spacing=6)


def note_box(draw, box, title, lines, hebrew=False):
    draw.rounded_rectangle(box, radius=18, fill=LIGHT_GOLD, outline="#E4C56A", width=2)
    x1, y1, x2, _ = box
    title_text = rtl(title) if hebrew else title
    draw.text((x1 + 22, y1 + 18), title_text, font=FONT_LABEL_BOLD, fill=NAVY)
    y = y1 + 50
    for line in lines:
        t = rtl(line) if hebrew else line
        draw.text((x1 + 22, y), t, font=FONT_NOTE, fill=TEXT)
        y += 26


def draw_chart(language: str):
    hebrew = language == "he"
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    title = "Baby-Cry Alert Logic State Machine"
    if hebrew:
        title = rtl("מכונת מצבים ללוגיקת התרעת בכי תינוק")
    text_center(draw, (W / 2, 48), [title], [FONT_TITLE], fill=NAVY)

    nodes = {
        "idle": (80, 120, 300, 230),
        "possible": (385, 120, 605, 230),
        "confirmed": (690, 120, 910, 230),
        "alerted": (995, 120, 1215, 230),
        "cooldown": (995, 420, 1215, 530),
        "rearming": (690, 420, 910, 530),
    }

    if hebrew:
        labels = {
            "idle": ("IDLE", rtl("המתנה")),
            "possible": ("POSSIBLE_CRY", rtl("חשד לבכי")),
            "confirmed": ("CONFIRMED_CRY", rtl("בכי מאושר")),
            "alerted": ("ALERTED", rtl("נשלחה התרעה")),
            "cooldown": ("COOLDOWN", rtl("מניעת התרעות חוזרות")),
            "rearming": ("REARMING", rtl("הכנה לזיהוי מחדש")),
        }
    else:
        labels = {
            "idle": ("IDLE", "No cry suspicion"),
            "possible": ("POSSIBLE_CRY", "First high score"),
            "confirmed": ("CONFIRMED_CRY", "Cry confirmed"),
            "alerted": ("ALERTED", "Watch vibrates"),
            "cooldown": ("COOLDOWN", "No repeat alerts"),
            "rearming": ("REARMING", "Wait for low score"),
        }

    for key, box in nodes.items():
        fill = LIGHT_BLUE if key in {"possible", "confirmed"} else WHITE
        if key in {"cooldown", "rearming"}:
            fill = GRAY
        if key == "alerted":
            fill = "#E8F7EF"
        rounded_node(draw, box, *labels[key], fill=fill)

    # Main path
    arrow(draw, [(300, 175), (385, 175)])
    arrow(draw, [(605, 175), (690, 175)])
    arrow(draw, [(910, 175), (995, 175)])
    arrow(draw, [(1105, 230), (1105, 420)])
    arrow(draw, [(995, 475), (910, 475)])
    arrow(draw, [(690, 475), (190, 475), (190, 230)])

    # Return from possible to idle.
    arrow(draw, [(385, 215), (300, 215)], fill=BLUE)

    if hebrew:
        label_box(draw, (342, 92), ["ציון בכי מוחלק ≥ סף הפעלה"], hebrew=True, width=260)
        label_box(draw, (648, 92), ["כלל התמדה התקיים", "מספיק פריימים מעל הסף"], hebrew=True, width=270)
        label_box(draw, (954, 92), ["שליחת התרעה לשעון"], hebrew=True, width=230)
        label_box(draw, (1225, 325), ["ההתרעה נשלחה", "השעון רוטט"], hebrew=True, width=210)
        label_box(draw, (954, 392), ["זמן הקירור הסתיים", "נדרש ניקוי לפני אירוע חדש"], hebrew=True, width=300)
        label_box(draw, (415, 555), ["הציון נשאר מתחת לסף הניקוי", "למשך זמן ההכנה מחדש"], hebrew=True, width=360)
        label_box(draw, (342, 258), ["הציון ירד לפני אישור"], hebrew=True, width=250)
        note_box(
            draw,
            (370, 635, 1045, 760),
            "מניעת התרעות כפולות",
            [
                "אם אותו אירוע בכי ממשיך, המערכת נשארת במסלול שאינו מצב המתנה.",
                "לא נשלחת התרעה נוספת עד שהציון יורד ונשלם שלב ההכנה מחדש.",
                "לכן ציון גבוה יחיד אינו מספיק כדי להעיר את ההורה.",
            ],
            hebrew=True,
        )
    else:
        label_box(draw, (342, 92), ["Smoothed cry score", ">= trigger threshold"], width=245)
        label_box(draw, (648, 92), ["Persistence rule satisfied", "enough frames above threshold"], width=305)
        label_box(draw, (954, 92), ["Send alert to smartwatch"], width=245)
        label_box(draw, (1225, 325), ["Alert sent", "watch vibrates"], width=200)
        label_box(draw, (954, 392), ["Cooldown ended", "wait for low score before reset"], width=310)
        label_box(draw, (415, 555), ["Score stays below clear threshold", "for rearming duration"], width=360)
        label_box(draw, (342, 258), ["Score falls below trigger", "before confirmation"], width=265)
        note_box(
            draw,
            (370, 635, 1045, 760),
            "Duplicate-alert prevention",
            [
                "If the same cry event continues, the system stays in a non-idle path.",
                "No new alert is sent until the score clears and rearming completes.",
                "A single high score is not enough to wake the parent.",
            ],
        )

    return img


def svg_text(x, y, lines, size=20, bold=False, anchor="middle", rtl_dir=False):
    weight = "700" if bold else "400"
    direction = ' direction="rtl" unicode-bidi="plaintext"' if rtl_dir else ""
    tspans = []
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else size * 1.25
        tspans.append(
            f'<tspan x="{x}" dy="{dy}">{escape(line)}</tspan>'
        )
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{TEXT}"{direction}>'
        + "".join(tspans)
        + "</text>"
    )


def svg_node(box, title, subtitle, fill=WHITE, rtl_dir=False):
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    return "\n".join(
        [
            f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" rx="22" fill="{fill}" stroke="{BORDER}" stroke-width="3"/>',
            svg_text(cx, y1 + 45, [title], 24, True, rtl_dir=False),
            svg_text(cx, y1 + 78, [subtitle], 20, False, rtl_dir=rtl_dir),
        ]
    )


def svg_arrow(points, color=NAVY):
    d = " ".join([("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(points)])
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="3" marker-end="url(#arrow)"/>'


def build_svg(language: str) -> str:
    hebrew = language == "he"
    nodes = {
        "idle": (80, 120, 300, 230),
        "possible": (385, 120, 605, 230),
        "confirmed": (690, 120, 910, 230),
        "alerted": (995, 120, 1215, 230),
        "cooldown": (995, 420, 1215, 530),
        "rearming": (690, 420, 910, 530),
    }
    if hebrew:
        title = "מכונת מצבים ללוגיקת התרעת בכי תינוק"
        labels = {
            "idle": ("IDLE", "המתנה"),
            "possible": ("POSSIBLE_CRY", "חשד לבכי"),
            "confirmed": ("CONFIRMED_CRY", "בכי מאושר"),
            "alerted": ("ALERTED", "נשלחה התרעה"),
            "cooldown": ("COOLDOWN", "מניעת התרעות חוזרות"),
            "rearming": ("REARMING", "הכנה לזיהוי מחדש"),
        }
    else:
        title = "Baby-Cry Alert Logic State Machine"
        labels = {
            "idle": ("IDLE", "No cry suspicion"),
            "possible": ("POSSIBLE_CRY", "First high score"),
            "confirmed": ("CONFIRMED_CRY", "Cry confirmed"),
            "alerted": ("ALERTED", "Watch vibrates"),
            "cooldown": ("COOLDOWN", "No repeat alerts"),
            "rearming": ("REARMING", "Wait for low score"),
        }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        "<defs>",
        f'<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="{NAVY}"/></marker>',
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="{WHITE}"/>',
        svg_text(W / 2, 55, [title], 34, True, rtl_dir=hebrew),
    ]
    for key, box in nodes.items():
        fill = LIGHT_BLUE if key in {"possible", "confirmed"} else WHITE
        if key in {"cooldown", "rearming"}:
            fill = GRAY
        if key == "alerted":
            fill = "#E8F7EF"
        parts.append(svg_node(box, *labels[key], fill=fill, rtl_dir=hebrew))
    parts.extend(
        [
            svg_arrow([(300, 175), (385, 175)]),
            svg_arrow([(605, 175), (690, 175)]),
            svg_arrow([(910, 175), (995, 175)]),
            svg_arrow([(1105, 230), (1105, 420)]),
            svg_arrow([(995, 475), (910, 475)]),
            svg_arrow([(690, 475), (190, 475), (190, 230)]),
            svg_arrow([(385, 215), (300, 215)], BLUE),
        ]
    )
    # SVG labels are intentionally concise; PNG contains the full readable version.
    if hebrew:
        label_lines = [
            (342, 88, ["ציון בכי מוחלק ≥ סף הפעלה"], 18),
            (648, 88, ["כלל התמדה התקיים"], 18),
            (954, 88, ["שליחת התרעה לשעון"], 18),
            (1220, 325, ["התרעה נשלחה"], 18),
            (954, 392, ["הקירור הסתיים; נדרש ניקוי"], 18),
            (415, 555, ["הציון נמוך במשך זמן ההכנה מחדש"], 18),
            (342, 258, ["הציון ירד לפני אישור"], 18),
        ]
        note_title = "מניעת התרעות כפולות"
        note = [
            "אם אותו אירוע בכי ממשיך, המערכת נשארת במסלול שאינו IDLE.",
            "לא נשלחת התרעה נוספת עד שהציון יורד ונשלם שלב REARMING.",
        ]
    else:
        label_lines = [
            (342, 88, ["Smoothed score >= trigger threshold"], 18),
            (648, 88, ["Persistence rule satisfied"], 18),
            (954, 88, ["Send alert to smartwatch"], 18),
            (1220, 325, ["Alert sent; watch vibrates"], 18),
            (954, 392, ["Cooldown ended; wait for low score"], 18),
            (415, 555, ["Low score remains for rearming duration"], 18),
            (342, 258, ["Score falls before confirmation"], 18),
        ]
        note_title = "Duplicate-alert prevention"
        note = [
            "If the same cry event continues, the system stays in a non-idle path.",
            "No new alert is sent until the score clears and rearming completes.",
        ]
    for x, y, lines, size in label_lines:
        parts.append(svg_text(x, y, lines, size, False, rtl_dir=hebrew))
    parts.append('<rect x="370" y="635" width="675" height="125" rx="18" fill="#FFF7E6" stroke="#E4C56A" stroke-width="2"/>')
    parts.append(svg_text(708, 670, [note_title], 20, True, rtl_dir=hebrew))
    parts.append(svg_text(708, 704, note, 18, False, rtl_dir=hebrew))
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for lang, stem in [("en", "state_chart"), ("he", "state_chart_hebrew")]:
        draw_chart(lang).save(OUT_DIR / f"{stem}.png")
        (OUT_DIR / f"{stem}.svg").write_text(build_svg(lang), encoding="utf-8")
        print(OUT_DIR / f"{stem}.png")
        print(OUT_DIR / f"{stem}.svg")


if __name__ == "__main__":
    main()
