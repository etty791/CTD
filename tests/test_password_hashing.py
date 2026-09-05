from server.persistence.password_hashing import (
    SALT_BYTES,
    PasswordRecord,
    hash_password,
    verify_password,
)

PASSWORD = "correct horse battery staple"


class TestHashPassword:
    def test_returns_password_record(self):
        assert isinstance(hash_password(PASSWORD), PasswordRecord)

    def test_salt_length(self):
        record = hash_password(PASSWORD)
        assert len(record.salt) == SALT_BYTES

    def test_distinct_salts_and_hashes(self):
        first = hash_password(PASSWORD)
        second = hash_password(PASSWORD)
        assert first.salt != second.salt
        assert first.password_hash != second.password_hash


class TestVerifyPassword:
    def test_roundtrip_true(self):
        record = hash_password(PASSWORD)
        assert verify_password(PASSWORD, record.salt, record.password_hash)

    def test_wrong_password_false(self):
        record = hash_password(PASSWORD)
        assert not verify_password("wrong", record.salt, record.password_hash)
