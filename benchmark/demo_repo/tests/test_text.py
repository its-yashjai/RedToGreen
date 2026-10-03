from shopkit.text import count_words, initials, is_palindrome, slugify, truncate


def test_slugify():
    assert slugify("Phone Case (Blue)!") == "phone-case-blue"
    assert slugify("  USB-C   Cable ") == "usb-c-cable"


def test_truncate():
    assert truncate("short", 10) == "short"
    assert truncate("exactly10!", 10) == "exactly10!"
    assert truncate("a long product title", 10) == "a long ..."
    assert len(truncate("a long product title", 10)) == 10


def test_count_words():
    assert count_words("fast  wireless charger") == 3
    assert count_words("") == 0


def test_is_palindrome():
    assert is_palindrome("Madam")
    assert is_palindrome("A man, a plan, a canal: Panama")
    assert not is_palindrome("charger")


def test_initials():
    assert initials("ravi kumar sharma") == "RKS"
