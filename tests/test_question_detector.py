"""Question detection for natural Gen Z chat without a question mark."""
import pytest

from ai.question_detector import count_questions, detect_question, is_question

QUESTIONS = [
    # the four from the spec
    "b hay đi đâu á",
    "nay b đi học hả",
    "b thường nghe nhạc gì z",
    "cuối tuần b làm gì",
    # wh-words
    "b làm bên gì á",
    "b tên gì z",
    "mấy giờ b tan làm",
    "b bao nhiêu tuổi",
    "b vào ĐN bao lâu rồi",
    "sao b nhắn ít z",
    "b thích quán nào",
    "ủa người đẹp này ở đâu ra z :))",
    "ai chở b đi z",
    # central dialect (persona is Đà Nẵng/Huế)
    "ẩn danh chi vậy fen",
    "b ở mô ra z",
    "làm răng mà lâu rứa",
    # final particles
    "b ăn cơm chưa",
    "nay b bận k",
    "b có hay đi biển khum",
    "nay đi cf k ạ",
    "b vào ĐN lâu chưa",
    "nay làm tới mấy giờ z",
    # structure
    "team lẩu hay nướng :))",
    "hay là ngồi nhà chill xíu thôi",
    "b hay cf hay thích ở nhà hơn",
    "b thích đi chơi hay ở nhà",
    "kể nghe coi",
    # multi-clause with emoticon
    "chưa hả :)) tối ni b tính làm gì z",
    "tui nói lộn xí, ý là b thích đi cf k",
    "vibe b dễ thương thật á, nay b làm gì z",
    # explicit mark still works
    "thiệt hả?",
    "ừ?",
]

NOT_QUESTIONS = [
    "tui 2k4 á",
    "z cũng dc",
    "ủa thiệt hả :))",
    "z hả",
    "chưa hả :))",
    "vậy à",
    "em chưa",
    "mình chưa",
    "học cả ngày bảo sao k đuối :))",
    "tui cũng hay đi cf á",
    "nói chuyện hay ghê",
    "phim này hay lắm",
    "vibe b dễ thương thật á",
    "không sao đâu",
    "chả biết gì hết",
    "tui đâu có đi",
    "tui không đi đâu cả",
    "biết ngay mà =))",
    "ờ ha =)) z trường hợp ni cho cầm",
    "hôm nào rảnh đi cf",
    "mai tui đi bida với bạn á",
    "ý tui là mấy lần á, nãy tui nói lộn :))",
    "nghe cũng vui á, tui cũng hay lượn phố tối",
    "ghê nha",
    "",
]


@pytest.mark.parametrize("text", QUESTIONS)
def test_detects_questions(text):
    assert is_question(text), text


@pytest.mark.parametrize("text", NOT_QUESTIONS)
def test_ignores_statements_and_reactions(text):
    assert not is_question(text), (text, detect_question(text))


def test_reason_is_reported():
    assert detect_question("b hay đi đâu á").reason == "wh-word"
    assert detect_question("nay b đi học hả").reason == "final-particle"
    assert detect_question("team lẩu hay nướng").reason == "alternative"
    assert detect_question("ừ?").reason == "question-mark"


def test_history_catches_reworded_repeat():
    asked = ["b vào đn lâu chưa"]
    assert not is_question("vào đn được lâu tui thấy rồi ha")          # plain statement
    assert is_question("b vào đn lâu rồi ha", asked_history=asked)     # reworded copy of an old question


def test_count_questions_catches_stacked_questions_without_marks():
    assert count_questions("b làm gì, ở đâu, lâu chưa") >= 2
    assert count_questions("b làm gì? ở đâu?") == 2
    assert count_questions("chưa hả :)) tối ni b tính làm gì z") == 1
    assert count_questions("ghê nha") == 0
