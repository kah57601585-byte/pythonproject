"""OPIc-style question bank and random selection by difficulty level.

Levels follow the OPIc self-assessment scale (1-6). Higher levels unlock
harder question types (comparison, role-play, social issues), mirroring how
the real test raises difficulty for higher self-assessment choices.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

# Question types, roughly ordered by difficulty.
QUESTION_TYPES: dict[str, str] = {
    "self_intro": "자기소개",
    "description": "묘사",
    "routine": "루틴/습관",
    "past_experience": "과거 경험",
    "comparison": "비교/변화",
    "roleplay": "롤플레이",
    "issue": "사회적 이슈/의견",
}

# Which types appear at each self-assessment level.
LEVEL_TYPES: dict[int, list[str]] = {
    1: ["self_intro", "description", "routine"],
    2: ["self_intro", "description", "routine"],
    3: ["description", "routine", "past_experience"],
    4: ["description", "routine", "past_experience", "comparison", "roleplay"],
    5: ["description", "past_experience", "comparison", "roleplay", "issue"],
    6: ["description", "past_experience", "comparison", "roleplay", "issue"],
}

LEVEL_INFO: dict[int, dict[str, str]] = {
    1: {"target": "NL~NM", "desc": "단어 위주로 말할 수 있어요"},
    2: {"target": "NH~IL", "desc": "간단한 문장으로 말할 수 있어요"},
    3: {"target": "IL~IM1", "desc": "익숙한 주제는 문장을 이어서 말할 수 있어요"},
    4: {"target": "IM2~IM3", "desc": "대부분의 일상 주제를 말할 수 있어요"},
    5: {"target": "IH", "desc": "경험과 비교를 자세히 말할 수 있어요"},
    6: {"target": "IH~AL", "desc": "어떤 주제든 논리적으로 길게 말할 수 있어요"},
}

# Background-survey topics. "general" holds the 돌발 (unexpected) topics.
TOPICS: dict[str, str] = {
    "home": "집/동네",
    "music": "음악 감상",
    "movies": "영화 보기",
    "cafe": "카페 가기",
    "park": "공원 가기",
    "jogging": "조깅/걷기",
    "travel": "국내 여행",
    "shopping": "쇼핑",
    "general": "돌발 주제",
}


@dataclass(frozen=True)
class Question:
    id: str
    topic: str
    qtype: str
    text: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["topic_label"] = TOPICS.get(self.topic, self.topic)
        d["qtype_label"] = QUESTION_TYPES.get(self.qtype, self.qtype)
        return d


_RAW: list[tuple[str, str, str]] = [
    # (topic, type, text)
    ("general", "self_intro", "Let's start the interview now. Tell me a little bit about yourself."),
    ("general", "self_intro", "Please introduce yourself. What kind of person are you, and what do you do these days?"),

    ("home", "description", "Describe your home. What does it look like? How many rooms are there, and which room do you like the most?"),
    ("home", "routine", "What do you usually do at home on weekdays and on weekends? Tell me about your typical routine at home."),
    ("home", "past_experience", "Tell me about a time when you had to fix or change something in your home. What happened and how did you handle it?"),
    ("home", "comparison", "Compare the home you live in now with the home you lived in when you were a child. What has changed?"),
    ("home", "roleplay", "You are looking for a new apartment. Call a real estate agent and ask three or four questions about an apartment you are interested in."),
    ("home", "issue", "Housing prices have become a big issue in many countries. What are people in your country concerned about when it comes to housing?"),
    ("home", "description", "Describe your neighborhood. What can people see and do there?"),

    ("music", "description", "You indicated that you enjoy listening to music. What kind of music do you like, and who are your favorite singers or composers?"),
    ("music", "routine", "When and where do you usually listen to music? What devices do you use?"),
    ("music", "past_experience", "Tell me about a memorable concert or live performance you went to. Who did you go with and what made it special?"),
    ("music", "comparison", "How has the way people listen to music changed over the years? Compare how people listened to music in the past with how they do it today."),
    ("music", "roleplay", "You want to buy tickets for a concert. Call the ticket office and ask some questions about the concert and the tickets."),
    ("music", "issue", "Some people say streaming services are unfair to musicians. What do you think about this issue?"),

    ("movies", "description", "You said you like watching movies. What genres do you like and why? Tell me about your favorite movie."),
    ("movies", "routine", "What do you usually do before and after watching a movie? Describe your routine when you go to the movies."),
    ("movies", "past_experience", "Tell me about the most memorable movie you have seen recently. What was it about and why was it memorable?"),
    ("movies", "comparison", "Compare the movies that were popular when you were younger with the movies that are popular now."),
    ("movies", "roleplay", "You want to watch a movie with a friend this weekend. Call your friend and ask questions to make plans."),
    ("movies", "issue", "Many people now watch movies at home instead of in theaters. How do you think this trend is affecting the movie industry?"),

    ("cafe", "description", "Describe a cafe that you often go to. Where is it, what does it look like, and why do you like it?"),
    ("cafe", "routine", "What do you usually do when you go to a cafe? Who do you go with and what do you order?"),
    ("cafe", "past_experience", "Tell me about a memorable experience you had at a cafe. What happened?"),
    ("cafe", "comparison", "How are cafes today different from cafes a few years ago? Talk about the changes you have noticed."),
    ("cafe", "roleplay", "You ordered a drink at a cafe, but you got the wrong drink. Explain the situation to the staff and suggest two or three ways to solve the problem."),

    ("park", "description", "Describe a park you like to go to. Where is it and what does it look like?"),
    ("park", "routine", "What do you usually do when you go to the park? How often do you go and with whom?"),
    ("park", "past_experience", "Tell me about something interesting or unexpected that happened at a park."),
    ("park", "comparison", "Compare parks in your country now with parks when you were a child."),

    ("jogging", "description", "You indicated that you go jogging or walking. Where do you usually go and why do you like that place?"),
    ("jogging", "routine", "Describe your jogging or walking routine. When do you go, how long do you exercise, and what do you do before and after?"),
    ("jogging", "past_experience", "Tell me about how you first started jogging or walking for exercise. Why did you start?"),
    ("jogging", "roleplay", "You want to join a running club. Call the club and ask three or four questions about joining."),
    ("jogging", "issue", "Many people say they are too busy to exercise. What do you think people can do to stay healthy?"),

    ("travel", "description", "Tell me about a place in your country that you like to travel to. What is special about it?"),
    ("travel", "routine", "What do you usually do to prepare for a trip? Describe the steps from planning to packing."),
    ("travel", "past_experience", "Tell me about a memorable trip you took. Where did you go, who did you go with, and what happened?"),
    ("travel", "past_experience", "Tell me about a time when something went wrong during a trip. What happened and how did you deal with it?"),
    ("travel", "comparison", "How has traveling in your country changed compared to ten years ago?"),
    ("travel", "roleplay", "You are planning a trip and want to book a hotel. Call the hotel and ask three or four questions about the rooms and facilities."),

    ("shopping", "description", "Describe a store or shopping area you often go to. What does it look like?"),
    ("shopping", "routine", "How do you usually shop? Do you prefer shopping online or in stores? Why?"),
    ("shopping", "past_experience", "Tell me about a time when you bought something and had a problem with it. What did you do?"),
    ("shopping", "comparison", "Compare shopping in the past with shopping today. What are the biggest differences?"),
    ("shopping", "roleplay", "You bought a jacket online, but it is the wrong size. Call the store, explain the problem, and suggest two or three ways to solve it."),
    ("shopping", "issue", "Some people worry that online shopping is hurting small local stores. What is your opinion?"),

    # 돌발 (unexpected) topics
    ("general", "description", "Tell me about the weather in your country. How is it different in each season?"),
    ("general", "description", "Describe a holiday that is important in your country. What do people usually do?"),
    ("general", "routine", "How do you usually use your smartphone during the day? What apps do you use most often?"),
    ("general", "past_experience", "Tell me about a recent day when you went to a bank. What did you do there?"),
    ("general", "past_experience", "Tell me about a time when you had to deal with bad weather. What happened?"),
    ("general", "comparison", "How has technology changed the way people communicate? Compare how people communicated in the past and today."),
    ("general", "roleplay", "You have an appointment with a doctor, but you can't make it. Call the clinic, explain your situation, and reschedule."),
    ("general", "issue", "What are some environmental problems that people in your country are worried about? What should be done about them?"),
    ("general", "issue", "Many young people find it hard to get a job these days. Why do you think this is happening?"),
]

BANK: list[Question] = [
    Question(id=f"q{i:03d}", topic=t, qtype=qt, text=txt)
    for i, (t, qt, txt) in enumerate(_RAW, start=1)
]


def clamp_level(level: int) -> int:
    return max(1, min(6, int(level)))


def candidates(level: int, topics: list[str] | None = None) -> list[Question]:
    """Questions allowed for this level and (optionally) chosen survey topics."""
    allowed_types = set(LEVEL_TYPES[clamp_level(level)])
    chosen = set(topics or []) or set(TOPICS)
    chosen.add("general")  # unexpected topics can always appear, like the real test
    return [q for q in BANK if q.qtype in allowed_types and q.topic in chosen]


def pick_question(
    level: int,
    topics: list[str] | None = None,
    exclude_ids: list[str] | None = None,
    rng: random.Random | None = None,
) -> Question:
    """Pick a random question, avoiding recently asked ones when possible."""
    rng = rng or random.Random()
    pool = candidates(level, topics)
    excluded = set(exclude_ids or [])
    fresh = [q for q in pool if q.id not in excluded]
    pool = fresh or pool
    # Pick the type first so rare types (e.g. role-play) still come up often.
    qtype = rng.choice(sorted({q.qtype for q in pool}))
    return rng.choice([q for q in pool if q.qtype == qtype])
