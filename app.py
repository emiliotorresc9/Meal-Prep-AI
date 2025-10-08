from flask import Flask, render_template, request, jsonify
import json, os, random
import smtplib
from email.mime.text import MIMEText
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


app = Flask(__name__)

# ---------- Data helpers ----------
def load_recipes():
    with open(os.path.join("data", "recipes.json"), "r", encoding="utf-8") as f:
        return json.load(f)

def find_recipe(rid):
    for r in load_recipes():
        if r.get("id") == rid:
            return r
    return None

# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.post("/suggest")
def suggest():
    """
    Input JSON:
    {
      "meal_type": "breakfast|lunch|dinner",
      "goals": ["low_budget","quick_meal","lose_fat","gain_muscle","high_protein",
                "vegan","vegetarian","gluten_free","keto_friendly","meal_prep",
                "dairy_free","surprise_me"],
      "limit": 6
    }
    """
    data = request.get_json() or {}
    meal_type = (data.get("meal_type") or "").strip().lower()
    goals = [g.strip().lower() for g in (data.get("goals") or [])]
    limit = int(data.get("limit") or 6)

    recipes = load_recipes()

    # 1) meal_type filter
    if meal_type:
        recipes = [r for r in recipes if (r.get("meal_type") or "").lower() == meal_type]

    # 2) goals filter (ALL if possible, else ANY)
    if goals:
        def has_all_goals(r):
            rg = [g.lower() for g in (r.get("goal") or [])]
            return all(g in rg for g in goals)

        strict = [r for r in recipes if has_all_goals(r)]
        if strict:
            recipes = strict
        else:
            def has_any_goal(r):
                rg = [g.lower() for g in (r.get("goal") or [])]
                return any(g in rg for g in goals)
            recipes = [r for r in recipes if has_any_goal(r)]

    # 3) Surprise
    if goals == ["surprise_me"]:
        random.shuffle(recipes)

    # 4) Simple sorting heuristic
    sorting_goal = None
    for g in goals:
        if g in {"low_budget","quick_meal","gain_muscle","high_protein","lose_fat","keto_friendly","low_carb"}:
            sorting_goal = g
            break

    def safe_get(d, path, default=999999):
        try:
            cur = d
            for p in path:
                cur = cur[p]
            return cur
        except Exception:
            return default

    if sorting_goal == "low_budget":
        recipes.sort(key=lambda r: r.get("cost_per_serving_usd", 9999))
    elif sorting_goal == "quick_meal":
        recipes.sort(key=lambda r: r.get("time_min", 9999))
    elif sorting_goal in {"gain_muscle","high_protein"}:
        recipes.sort(key=lambda r: safe_get(r, ["macros","protein_g"], -9999), reverse=True)
    elif sorting_goal in {"lose_fat","keto_friendly","low_carb"}:
        recipes.sort(key=lambda r: safe_get(r, ["macros","kcal"], 9999))

    # 5) shape response
    selected = recipes[:limit]
    slim = [{
        "id": r["id"],
        "title": r["title"],
        "meal_type": r.get("meal_type"),
        "goal": r.get("goal", []),
        "cost_per_serving_usd": r.get("cost_per_serving_usd", r.get("cost_usd", 0.0)),
        "time_min": r.get("time_min", 20),
        "macros": r.get("macros", {}),
        "ingredients": r.get("ingredients", [])
    } for r in selected]

    return jsonify({"recipes": slim})

@app.post("/recipe")
def recipe():
    data = request.get_json() or {}
    rid = int(data.get("id", 0))
    pantry = [p.strip().lower() for p in data.get("pantry", [])]

    r = find_recipe(rid)
    if not r:
        return jsonify({"error": "recipe not found"}), 404

    shopping_delta = []
    for ing in r.get("ingredients", []):
        name = (ing.get("name") or "").lower()
        if name and name not in pantry:
            shopping_delta.append({"item": ing.get("name"), "qty": ing.get("qty"), "unit": ing.get("unit")})

    time_min = r.get("time_min", 20)

    return jsonify({
        "title": r["title"],
        "ingredients": r["ingredients"],
        "cost_usd": float(r.get("cost_per_serving_usd", r.get("cost_usd", 0.0))),
        "macros": r.get("macros", {}),
        "shopping_delta": shopping_delta,
        "time_min": time_min
    })

# ---------- AI endpoints (ENGLISH) ----------

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
You can include little helpful tips (heat level, timing, texture, etc.).
Be concise, warm, and clear.

Recipe context:
Title: {title}
Meal type: {meal_type}
Ingredients: {json.dumps(ingredients, ensure_ascii=False)}
Known data: {json.dumps(macros, ensure_ascii=False)}, time_min={time_min}
"""

    try:
        resp = client.responses.create(model="gpt-4.1-mini", input=prompt)
        message = resp.output_text.strip()

        # Ensure numbered steps are separated by line breaks if model compresses them
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
def email():
    data = request.get_json() or {}
    to = data.get("to")
    name = data.get("name", "there")
    title = data.get("title", "Selected Recipe")
    items = data.get("shopping_delta", [])
    total = float(data.get("total_estimated", 0.0))

    if not to:
        return jsonify({"ok": False, "error": "missing email"}), 400

    body_lines = [
        f"Hi {name},",
        f"Here’s your grocery list for '{title}':",
        ""
    ]
    if items:
        for i in items:
            qty = i.get("qty")
            unit = i.get("unit", "")
            body_lines.append(f"- {i['item']}: {qty} {unit}".strip())
    else:
        body_lines.append("- Nothing to buy — you have everything 🎉")
    body_lines += ["", f"Estimated total: ${total:.2f} USD", "", "Happy cooking!", "— MealPrepAI"]

    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASS = os.getenv("SMTP_PASS")
    SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "no-reply@mealprep.ai")

    if SMTP_USER and SMTP_PASS:
        try:
            msg = MIMEText("\n".join(body_lines))
            msg["Subject"] = f"MealPrepAI — Grocery List for {title}"
            msg["From"] = SMTP_FROM
            msg["To"] = to
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(msg["From"], [to], msg.as_string())
            return jsonify({"ok": True, "mode": "smtp"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    else:
        # Dry-run for demo
        return jsonify({"ok": True, "mode": "dry_run"})

if __name__ == "__main__":
    app.run(debug=True)
