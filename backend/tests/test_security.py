from app.core.security import create_token,decode_token,hash_password,verify_password
def test_password_roundtrip():
    hashed=hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple",hashed)
    assert not verify_password("wrong",hashed)
def test_token_roundtrip(): assert decode_token(create_token("abc"))=="abc"
