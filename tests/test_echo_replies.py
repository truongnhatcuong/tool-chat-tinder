from ai.quality import find_echo_replies


def test_echo_of_their_newest_message_is_rejected():
    assert find_echo_replies(["vậy là cũng vừa sức á"], ["vừa sức th"])
    assert find_echo_replies(["cầm 24/7 luôn hả =))"], ["muốn cầm 24/7"])


def test_reply_with_new_idea_passes():
    assert not find_echo_replies(["vừa sức thì ngon r, điểm cao là được :))"], ["vừa sức th"])
    assert not find_echo_replies(["leo núi ngon z, b leo có mệt k"], ["Mình thích đi leo núi"])


def test_no_new_text_means_no_check():
    assert not find_echo_replies(["vậy là dễ hả"], [])
