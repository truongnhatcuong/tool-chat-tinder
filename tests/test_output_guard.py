"""Regression tests built from real bad replies seen in production chats."""
from ai.output_guard import find_violations


def test_opener_with_anh_em_and_name_greeting_is_rejected():
    bad = "Chào Thu Hương nha :D Nụ cười của em nhìn tươi tắn ghê, thấy match là anh phải ghé qua chào liền nè!"
    assert find_violations([bad], [], is_opener=True, name="Thu Hương")


def test_hihi_start_and_fake_common_ground_rejected():
    assert find_violations(["hihi, giống nhau ghê =)) ủa b có thích đi chơi không?"], ["tớ à"])


def test_two_questions_in_one_turn_rejected():
    msgs = ["chưa hả :)) hôm ni b định đi đâu k?", "hay là ngồi nhà chill xíu thôi?"]
    assert find_violations(msgs, ["Em chưa :)))"])


def test_repeated_health_advice_rejected():
    assert find_violations(["học cả ngày thì tranh thủ nghỉ xíu nha :))"], ["học cả ngày nên mệt kk"])
    assert find_violations(["đừng cầm máy nữa nhé"], ["đang giải lao xíu vào ktr"])


def test_chatbot_question_rejected():
    assert find_violations(["thế em có đọc gì không?"], ["hả đọc k load về"])


def test_pronoun_allowed_only_when_they_used_it_first():
    assert find_violations(["em chưa hả :))"], ["chào bạn"])
    assert not find_violations(["anh cũng chưa :))"], ["anh ơi đi nhậu chưa", "em rảnh nè"])


def test_natural_replies_pass():
    good = [
        ["học cả ngày bảo sao k đuối :))"],
        ["ờ ha =)) z trường hợp ni cho cầm"],
        ["biết ngay mà =))"],
        ["ý tui là mấy lần á, nãy tui nói lộn :))"],
        ["chưa hả :)) tối ni b tính làm gì z?"],
    ]
    for msgs in good:
        assert find_violations(msgs, ["ừ"]) == [], msgs


def test_too_long_message_rejected():
    assert find_violations([" ".join(["chữ"] * 40)], [])


def test_light_compliments_with_followup_pass():
    good = [
        ["vibe b dễ thương thật á, nay b làm gì z?"],
        ["cười kiểu này dễ gây thương nhớ á :))"],
        ["ảnh này nhìn có duyên á, chụp ở đâu z?"],
    ]
    for msgs in good:
        assert find_violations(msgs, ["ừ"]) == [], msgs


def test_cheesy_compliment_still_rejected():
    assert find_violations(["Nụ cười của bạn là báu vật"], [])


def test_third_consecutive_question_rejected():
    prior = ["b ở ĐN lâu chưa?", "b làm bên gì á?"]
    assert find_violations(["b hay đi cf k?"], ["ừ"], recent_outgoing=prior)


def test_question_allowed_after_a_no_question_turn():
    prior = ["b ở ĐN lâu chưa?", "z hả, tui cũng hay đi cf :))"]
    assert not find_violations(["b hay đi cf k?"], ["ừ"], recent_outgoing=prior)


def test_no_question_reply_always_ok_after_two_questions():
    prior = ["b ở ĐN lâu chưa?", "b làm bên gì á?"]
    assert not find_violations(["z chắc cũng bận dữ :))"], ["ừ"], recent_outgoing=prior)
