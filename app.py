from flask import Flask, render_template, request, jsonify
import os, json, random, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI

# -------------------------
# Setup
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__, template_folder="templates", static_folder="static")


# -------------------------
# Routes
# -------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.post("/suggest")
def suggest():
    """
    Generates 3–5 recipe ideas from OpenAI based on user inputs.
    Input JSON:
    {
      "meal_type": "breakfast|lunch|dinner" | null,
      "goals": [ ... ],
      "comments": "free text" | null,
      "limit": int (3..6)
    }
    """
    data = request.get_json() or {}
    meal_type = (data.get("meal_type") or "").strip().lower()
    goals = data.get("goals") or []
    comments = (data.get("comments") or "").strip()
    limit = int(data.get("limit") or 5)
    limit = max(3, min(limit, 6))

    # Map some icons for fun tags
    emoji_map = {
        "breakfast": "🍳", "lunch": "🥪", "dinner": "🍽️",
        "low_budget": "🪙", "quick_meal": "⚡", "lose_fat": "🥗", "gain_muscle": "💪",
        "high_protein": "🧬", "vegan": "🌱", "vegetarian": "🥦", "gluten_free": "🌾",
        "keto_friendly": "🧈", "meal_prep": "📅", "dairy_free": "🥛❌", "surprise_me": "🎲"
    }

    # Build prompt
    prompt = f"""
You are a meal-planning assistant. Create between 3 and {limit} recipe ideas that match the user's request.

Return STRICT JSON (no prose) as:
{{
  "recipes": [
    {{
      "id": <int>,
      "title": <string>,
      "meal_type": <"breakfast"|"lunch"|"dinner">,
      "goal": [<snake_case goal tags>],
      "time_min": <int>,
      "cost_usd": <number>,
      "macros": {{"kcal": <int>, "protein_g": <int>, "carbs_g": <int>, "fat_g": <int>}},
      "ingredients": [{{"qty": <number|string|null>, "unit": <string|null>, "name": <string>}}, ...]
    }},
    ...
  ]
}}

Guidelines:
- Prefer simple, realistic dishes using common ingredients.
- Calorie estimate should be reasonable for the meal type.
- Ingredients list 6–12 items.
- Match goals if provided.
- If goals include "surprise_me", you may pick any style.
- meal_type must be one of breakfast/lunch/dinner. If none provided, choose what fits best the idea.

User inputs:
- meal_type: "{meal_type}"
- goals: {goals}
- comments: "{comments}"
"""

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0.8
        )
        # Parse JSON from the model output
        raw = resp.output_text.strip()
        # The model should return JSON; try to load it
        data_json = json.loads(raw)
        recipes = data_json.get("recipes", [])
    except Exception as e:
        # On failure, return empty list with error
        return jsonify({"recipes": [], "error": str(e)})

    # Cosmetic: attach first goal emoji into tags if missing, keep as-is otherwise
    for r in recipes:
        r.setdefault("goal", [])
        # ensure ids
        if "id" not in r:
            r["id"] = random.randint(100000, 999999)
        # normalize keys
        if "cost_per_serving_usd" in r and "cost_usd" not in r:
            r["cost_usd"] = r.get("cost_per_serving_usd")

    return jsonify({"recipes": recipes})


@app.post("/ai/instructions")
def ai_instructions():
    """
    Input: { "recipe": { title, meal_type, ingredients[], macros?, time_min? } }
    Output: { message: str } — full friendly message from Emil-ia
    """
    data = request.get_json() or {}
    r = data.get("recipe") or {}

    title = r.get("title", "Recipe")
    meal_type = r.get("meal_type", r.get("meal", ""))
    ingredients = r.get("ingredients", [])
    macros = r.get("macros", {})
    time_min = r.get("time_min")
    cost_usd = r.get("cost_usd", r.get("cost_per_serving_usd"))

    prompt = f"""
You are Emil-ia, a friendly cooking assistant for MealPrepAI.

Your job:
- Greet the user once: "Hi, I'm Emil-ia! I'm here to guide you through preparing <title>."
- Then give 5–8 detailed cooking steps.
- Each step MUST appear on its own line, numbered clearly as:
  1. ...
  2. ...
  3. ...
  (etc)
- Add a blank line between each step for readability.
- End with: "If you have any questions, let me know!"

Use only ENGLISH, natural friendly tone (like a human cooking coach).
Be concise, warm, and clear.

Recipe context:
Title: {title}
Meal type: {meal_type}
Ingredients: {json.dumps(ingredients, ensure_ascii=False)}
Known data: {json.dumps(macros, ensure_ascii=False)}, time_min={time_min}, cost_usd={cost_usd}
"""

    try:
        resp = client.responses.create(model="gpt-4.1-mini", input=prompt)
        message = (resp.output_text or "").strip()
        # Make sure steps break lines in case model compresses
        formatted = message.replace(". ", ".\n").replace("  ", " ").strip()
        return jsonify({"message": formatted})
    except Exception as e:
        return jsonify({
            "message": "(AI error) I couldn’t load the instructions right now.",
            "error": str(e)
        }), 500


@app.post("/ai/chat")
def ai_chat():
    """
    Input: { message: string, recipe?: {title, ingredients[]} }
    Output: { reply: string }
    """
    data = request.get_json() or {}
    msg = (data.get("message") or "").strip()
    r = data.get("recipe") or {}
    title = r.get("title", "Recipe")
    ingredients = r.get("ingredients", [])

    coach = (
        "You are Emil-ia, a helpful cooking coach. "
        "Always reply in ENGLISH, concise, friendly, with practical substitutions when relevant.\n"
        f"Recipe context: {title}\n"
        f"Ingredients: {json.dumps(ingredients, ensure_ascii=False)}\n"
        f"User message: {msg}"
    )

    try:
        resp = client.responses.create(model="gpt-4.1-mini", input=coach)
        return jsonify({"reply": (resp.output_text or "").strip()})
    except Exception as e:
        return jsonify({"reply": f"(error) {e}"}), 500


@app.post("/email")
def email_send():
    """
    Sends recipe + macros + ingredients + instructions to user's email.
    Input:
    {
      "to": "user@example.com",
      "name": "User",
      "recipe": {title, time_min?, cost_usd?, macros?, ingredients[]},
      "instructions": "<text>"
    }
    """
    data = request.get_json() or {}
    to = (data.get("to") or "").strip()
    name = data.get("name") or "there"
    recipe = data.get("recipe") or {}
    instructions = (data.get("instructions") or "").strip()

    if not to:
        return jsonify({"ok": False, "error": "Missing recipient email"}), 400

    title = recipe.get("title", "Selected Recipe")
    time_min = recipe.get("time_min")
    cost_usd = recipe.get("cost_usd", recipe.get("cost_per_serving_usd"))
    macros = recipe.get("macros", {})
    ingredients = recipe.get("ingredients", [])

    macros_line = []
    if macros.get("kcal"): macros_line.append(f'{macros["kcal"]} kcal')
    if macros.get("protein_g"): macros_line.append(f'{macros["protein_g"]}g protein')
    if macros.get("carbs_g"):   macros_line.append(f'{macros["carbs_g"]}g carbs')
    if macros.get("fat_g"):     macros_line.append(f'{macros["fat_g"]}g fat')
    macros_line = " • ".join(macros_line) if macros_line else "—"

    # Plain text body
    text_lines = [
        f"Hi {name}, I’m Emil-ia 👋",
        "",
        f"Here’s your recipe: {title}",
        f"Time: ~{time_min} min" if time_min else "",
        f"Estimated cost: ${cost_usd:.2f}" if isinstance(cost_usd, (int, float)) else "",
        f"Macros: {macros_line}",
        "",
        "Ingredients:"
    ]
    if ingredients:
        for i in ingredients:
            qty = i.get("qty")
            unit = i.get("unit", "")
            nm = i.get("name") or ""
            text_lines.append(f"- {qty or ''} {unit} {nm}".strip())
    else:
        text_lines.append("- (not provided)")
    text_lines += ["", "Instructions:", instructions, "", "Happy cooking!", "— MealPrepAI"]

    text_body = "\n".join([ln for ln in text_lines if ln is not None])

    # Simple HTML body
    def esc(s): 
        return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    ing_html = "".join(
        f"<li>{esc(str(i.get('qty') or ''))} {esc(i.get('unit') or '')} {esc(i.get('name') or '')}</li>"
        for i in ingredients
    ) or "<li>(not provided)</li>"
    instr_html = "<br>".join(esc(instructions).splitlines())
    html_body = f"""
<!doctype html>
<html>
  <body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a;">
    <p>Hi {esc(name)}, I’m <b>Emil-ia</b> 👋</p>
    <p>Here’s your recipe:</p>
    <h2 style="margin:8px 0 4px 0">{esc(title)}</h2>
    <p style="margin:0 0 8px 0;color:#334155">
      {f"Time: ~{time_min} min • " if time_min else ""}{f"Estimated cost: ${cost_usd:.2f} • " if isinstance(cost_usd,(int,float)) else ""}Macros: {esc(macros_line)}
    </p>
    <h3 style="margin:16px 0 8px 0">Ingredients</h3>
    <ul style="margin-top:0">{ing_html}</ul>
    <h3 style="margin:16px 0 8px 0">Instructions</h3>
    <p style="white-space:pre-wrap">{instr_html}</p>
    <p style="margin-top:16px">Happy cooking!<br>— MealPrepAI</p>
  </body>
</html>
"""

    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASS = os.getenv("SMTP_PASS")
    SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "no-reply@mealprep.ai")

    if not SMTP_USER or not SMTP_PASS:
        # Dry-run for local testing
        return jsonify({"ok": True, "mode": "dry_run", "preview": text_body[:400] + ("..." if len(text_body) > 400 else "")})

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"MealPrepAI — {title}"
        msg["From"] = SMTP_FROM
        msg["To"] = to

        part_text = MIMEText(text_body, "plain", "utf-8")
        part_html = MIMEText(html_body, "html", "utf-8")
        msg.attach(part_text)
        msg.attach(part_html)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(msg["From"], [to], msg.as_string())
        return jsonify({"ok": True, "mode": "smtp"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
