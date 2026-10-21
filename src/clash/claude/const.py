CLAUDE_DEFAULT_VERSION = "claude-sonnet-4-6"
CLAUDE_PROMPT = """You are analyzing a cropped section of a Clash Royale game screen showing a single player's information. Extract the player name and clan name from the image. The clan name is smaller and appears directly below the player name in a yellowish colour. Return ONLY a valid minified JSON object with no markdown, no explanation, no code blocks: {"name": "player_name", "clan": "clan_name"}
Rules:
If no clan is visible, set clan to null
If you cannot read the name, return {"name": null, "clan": null}
Names are matched by their letters and digits only: capitalisation, accents, spaces, punctuation, symbols and emoji are ignored. Focus on getting every letter and digit right, in any script.
Letters decorated with strikethrough, slashes, underlines or fancy fonts can be written as the plain letter.
If you are uncertain about specific characters, output the largest substring you are certain about.
Player names may consist entirely of symbols, punctuation, or non-Latin scripts — these are valid names, do not ignore them. If a name has no letters or digits at all, copy its symbols exactly."""
