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

# Background Survey, modeled on the real OPIc survey.
# Each option is (topic_id, Korean label, English activity phrase used in question templates).
# A topic_id of None means the choice adds no question topic (e.g. "운동을 전혀 하지 않음").
SURVEY: list[dict] = [
    {"id": "job", "title": "1. 현재 귀하는 어느 분야에 종사하고 계십니까?", "kind": "single", "options": [
        ("work", "사업/회사", "your work"),
        ("work", "재택근무/재택사업", "your work"),
        ("teaching", "교사/교육자", "teaching"),
        (None, "군 복무", ""),
        (None, "일 경험 없음", ""),
    ]},
    {"id": "student", "title": "2. 현재 학생이십니까?", "kind": "single", "options": [
        ("school", "예", "going to school"),
        (None, "아니오", ""),
    ]},
    {"id": "housing", "title": "3. 현재 귀하는 어디에 살고 계십니까?", "kind": "single", "options": [
        ("home", "개인주택이나 아파트에 홀로 거주", "your home"),
        ("home", "친구나 룸메이트와 함께 주택이나 아파트에 거주", "your home"),
        ("home", "가족(배우자/자녀/기타 가족)과 함께 주택이나 아파트에 거주", "your home"),
        ("home", "학교 기숙사", "your home"),
        ("home", "군대 막사", "your home"),
    ]},
    {"id": "leisure", "title": "4. 귀하는 여가 활동으로 주로 무엇을 하십니까?", "kind": "multi", "options": [
        ("movies", "영화 보기", "watching movies"),
        ("club", "클럽/나이트클럽 가기", "going to clubs"),
        ("performance", "공연 보기", "watching performances such as plays and musicals"),
        ("concert", "콘서트 보기", "going to concerts"),
        ("museum", "박물관 가기", "visiting museums"),
        ("park", "공원 가기", "going to the park"),
        ("camping", "캠핑하기", "going camping"),
        ("beach", "해변 가기", "going to the beach"),
        ("sports_watching", "스포츠 관람", "watching sports games"),
        ("home_improvement", "주거 개선", "improving and decorating your home"),
        ("bar", "술집/바에 가기", "going to bars"),
        ("cafe", "카페/커피전문점 가기", "going to cafes"),
        ("games", "게임하기 (비디오, 카드, 보드, 휴대폰 등)", "playing games"),
        ("billiards", "당구 치기", "playing pool"),
        ("chess", "체스하기", "playing chess"),
        ("sns", "SNS에 글 올리기", "posting on social media"),
        ("texting", "친구들과 문자 대화하기", "texting with your friends"),
        ("test_prep", "시험 대비 과정 수강하기", "taking test preparation courses"),
        ("tv", "TV 시청하기", "watching TV"),
        ("reality_tv", "리얼리티쇼 시청하기", "watching reality shows"),
        ("news", "뉴스를 보거나 듣기", "watching or listening to the news"),
        ("cooking_shows", "요리 관련 프로그램 시청하기", "watching cooking shows"),
        ("shopping", "쇼핑하기", "going shopping"),
        ("driving", "차로 드라이브하기", "going for a drive"),
        ("spa", "스파/마사지샵 가기", "going to spas or massage shops"),
        ("job_hunting", "구직활동하기", "looking for a job"),
        ("volunteering", "자원봉사하기", "doing volunteer work"),
    ]},
    {"id": "hobby", "title": "5. 귀하의 취미나 관심사는 무엇입니까?", "kind": "multi", "options": [
        ("reading_kids", "아이에게 책 읽어주기", "reading books to children"),
        ("music", "음악 감상하기", "listening to music"),
        ("instrument", "악기 연주하기", "playing a musical instrument"),
        ("singing", "혼자 노래 부르거나 합창하기", "singing"),
        ("dancing", "춤추기", "dancing"),
        ("writing", "글쓰기 (편지, 단문, 시 등)", "writing"),
        ("drawing", "그림 그리기", "drawing or painting"),
        ("cooking", "요리하기", "cooking"),
        ("pets", "애완동물 기르기", "taking care of your pet"),
        ("stocks", "주식 투자하기", "investing in stocks"),
        ("newspaper", "신문 읽기", "reading newspapers"),
        ("travel_blogs", "여행 관련 잡지나 블로그 읽기", "reading travel magazines or blogs"),
        ("photography", "사진 촬영하기", "taking pictures"),
        ("reading", "독서", "reading books"),
    ]},
    {"id": "sport", "title": "6. 귀하는 주로 어떤 운동을 즐기십니까?", "kind": "multi", "options": [
        ("basketball", "농구", "playing basketball"),
        ("baseball", "야구/소프트볼", "playing baseball"),
        ("soccer", "축구", "playing soccer"),
        ("football", "미식축구", "playing American football"),
        ("hockey", "하키", "playing hockey"),
        ("cricket", "크리켓", "playing cricket"),
        ("golf", "골프", "playing golf"),
        ("volleyball", "배구", "playing volleyball"),
        ("tennis", "테니스", "playing tennis"),
        ("badminton", "배드민턴", "playing badminton"),
        ("table_tennis", "탁구", "playing table tennis"),
        ("swimming", "수영", "swimming"),
        ("cycling", "자전거", "riding a bike"),
        ("skiing", "스키/스노우보드", "skiing or snowboarding"),
        ("skating", "아이스 스케이트", "ice skating"),
        ("jogging", "조깅", "jogging"),
        ("walking", "걷기", "walking"),
        ("yoga", "요가", "doing yoga"),
        ("hiking", "하이킹/트레킹", "hiking"),
        ("fishing", "낚시", "fishing"),
        ("gym", "헬스", "working out at the gym"),
        (None, "운동을 전혀 하지 않음", ""),
    ]},
    {"id": "travel", "title": "7. 귀하는 어떤 휴가나 출장을 다녀온 경험이 있습니까?", "kind": "multi", "options": [
        ("business_trip", "국내 출장", "taking business trips in your country"),
        ("overseas_business", "해외 출장", "taking business trips overseas"),
        ("staycation", "집에서 보내는 휴가", "spending your vacation at home"),
        ("travel", "국내 여행", "traveling in your country"),
        ("overseas_travel", "해외 여행", "traveling abroad"),
    ]},
]

# Real test: at least 12 items across questions 4-7.
SURVEY_MIN_ACTIVITIES = 12

TOPICS: dict[str, str] = {"general": "돌발 주제"}
TOPIC_PHRASES: dict[str, str] = {}
for _section in SURVEY:
    for _tid, _label, _phrase in _section["options"]:
        if _tid and _tid not in TOPICS:
            TOPICS[_tid] = _label
            TOPIC_PHRASES[_tid] = _phrase
TOPICS.update({"work": "직장/일", "school": "학교/학업", "home": "집/거주지"})


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

    ("work", "description", "Tell me about the company or place where you work. What does your office look like, and what kind of work do you do?"),
    ("work", "routine", "Describe a typical workday for you, from the time you arrive at work until you go home."),
    ("work", "past_experience", "Tell me about a memorable project or a challenging situation you had at work. What happened and how did you handle it?"),
    ("work", "comparison", "How has your job or your workplace changed since you first started working there?"),
    ("work", "roleplay", "You need to work on a project with a new coworker. Call the coworker and ask three or four questions about the project."),
    ("work", "issue", "Many people talk about work-life balance these days. What are the issues related to work and life balance in your country?"),

    ("school", "description", "Tell me about your school. What does the campus look like, and what do you study?"),
    ("school", "routine", "Describe a typical day at school for you. What classes do you take and what do you do between classes?"),
    ("school", "past_experience", "Tell me about a memorable experience you had at school. What happened and why do you remember it?"),
    ("school", "comparison", "Compare the school you attend now with the school you went to when you were younger."),
    ("school", "roleplay", "You are working on a group project. Call a classmate and ask three or four questions to plan the project."),
    ("school", "issue", "What are some issues that students in your country are worried about these days?"),

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

# Templates fill in question types for survey topics that have no hand-written question of that type.
TEMPLATES: dict[str, list[str]] = {
    "description": [
        ("In the survey, you indicated that {p} is one of your activities. Tell me about it in detail. "
        "Where do you usually do it, and what is it like?"),
    ],
    "routine": [
        ("Tell me about your typical routine when it comes to {p}. How often do you do it, who do you do it with, "
        "and what do you usually do from start to finish?"),
    ],
    "past_experience": [
        ("Tell me about a memorable experience you had related to {p}. When was it, what happened, "
        "and why was it so memorable?"),
        "How did you first get started with {p}? Tell me the story of how it began and how it has gone since then.",
    ],
    "comparison": [
        "How has {p} changed for you over the years? Compare how it was when you first started with how it is now.",
    ],
    "roleplay": [
        ("I'd like to give you a situation and ask you to act it out. You want to try {p} together with a friend. "
        "Call your friend and ask three or four questions to make plans."),
        ("I'm sorry, but there is a problem I need you to resolve. Your plans related to {p} this weekend have been "
        "cancelled because of an unexpected problem. Call your friend, explain the situation, and suggest two or "
        "three alternatives."),
    ],
    "issue": [
        ("What are some issues or concerns that people in your country talk about related to {p}? "
        "Why do you think these issues matter?"),
    ],
}


def _build_bank() -> list[Question]:
    bank = [Question(id=f"q{i:03d}", topic=t, qtype=qt, text=txt) for i, (t, qt, txt) in enumerate(_RAW, start=1)]
    curated = {(q.topic, q.qtype) for q in bank}
    for topic, phrase in TOPIC_PHRASES.items():
        if topic in ("work", "school", "home"):
            continue
        for qtype, templates in TEMPLATES.items():
            if (topic, qtype) in curated:
                continue
            for n, template in enumerate(templates):
                text = template.format(p=phrase)
                text = text[0].upper() + text[1:]
                bank.append(Question(id=f"t-{topic}-{qtype}-{n}", topic=topic, qtype=qtype, text=text))
    return bank


BANK: list[Question] = _build_bank()


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
    """Pick a random question, avoiding recently asked ones when possible.

    Picks a topic first (so every survey choice comes up), then a question type, then a question.
    """
    rng = rng or random.Random()
    pool = candidates(level, topics)
    excluded = set(exclude_ids or [])
    pool = [q for q in pool if q.id not in excluded] or pool
    topic = rng.choice(sorted({q.topic for q in pool}))
    pool = [q for q in pool if q.topic == topic]
    qtype = rng.choice(sorted({q.qtype for q in pool}))
    return rng.choice([q for q in pool if q.qtype == qtype])
