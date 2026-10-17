"""ICAO 9303 machine-readable zone (MRZ).

TD3 (passports): two lines of 44 characters.
TD1 (ID cards):  three lines of 30 characters, on the back of the card.
"""

WEIGHTS = [7, 3, 1]

# OCR confuses look-alike characters. Where the format says "digit" or "letter", fix by position.
TO_DIGIT = str.maketrans("OQDIZSBG", "00012586")
TO_ALPHA = str.maketrans("0125", "OIZS")


def char_value(c):
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - 55  # A=10 ... Z=35
    return 0  # filler '<'


def check_digit(text):
    total = sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(text))
    return str(total % 10)


def fix_positions(line, digits, letters):
    chars = list(line)
    for i in digits:
        if i < len(chars):
            chars[i] = chars[i].translate(TO_DIGIT)
    for i in letters:
        if i < len(chars):
            chars[i] = chars[i].translate(TO_ALPHA)
    return "".join(chars)


def split_names(text):
    names = text.split("<<", 1)
    surname = names[0].replace("<", " ").strip()
    given = names[1].replace("<", " ").strip() if len(names) > 1 else ""
    return surname, given


def parse_td3(line1, line2):
    """Passport: split the two lines into fields and report which check digits pass."""
    line1, line2 = line1.ljust(44, "<")[:44], line2.ljust(44, "<")[:44]
    line2 = fix_positions(line2, [9, *range(13, 20), *range(21, 28), 42, 43], [10, 11, 12, 20])
    surname, given = split_names(line1[5:])
    number, dob, expiry = line2[0:9], line2[13:19], line2[21:27]
    composite = line2[0:10] + line2[13:20] + line2[21:43]
    fields = {"surname": surname, "given_names": given, "document_number": number.replace("<", ""),
              "nationality": line2[10:13], "date_of_birth": dob, "sex": line2[20], "expiry_date": expiry}
    checks = {"document_number": check_digit(number) == line2[9],
              "date_of_birth": check_digit(dob) == line2[19],
              "expiry_date": check_digit(expiry) == line2[27],
              "composite": check_digit(composite) == line2[43]}
    return fields, checks


def parse_td1(line1, line2, line3):
    """ID card: number on line 1, dates on line 2, name on line 3."""
    line1, line2, line3 = (line.ljust(30, "<")[:30] for line in (line1, line2, line3))
    line2 = fix_positions(line2, [*range(0, 7), *range(8, 15), 29], [7, 15, 16, 17])
    number, number_check = line1[5:14], line1[14]
    if number_check == "<":
        # Long document numbers overflow into the optional field; their check digit comes last
        extra = line1[15:].split("<", 1)[0]
        number, number_check = number + extra[:-1], extra[-1:]
    dob, expiry = line2[0:6], line2[8:14]
    composite = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
    surname, given = split_names(line3)
    fields = {"surname": surname, "given_names": given, "document_number": number.replace("<", ""),
              "nationality": line2[15:18], "date_of_birth": dob, "sex": line2[7], "expiry_date": expiry}
    checks = {"document_number": check_digit(number) == number_check,
              "date_of_birth": check_digit(dob) == line2[6],
              "expiry_date": check_digit(expiry) == line2[14],
              "composite": check_digit(composite) == line2[29]}
    return fields, checks
