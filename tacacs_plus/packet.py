import struct
from hashlib import md5

import six


def crypt(header, body_bytes, secret):
    """
    TACACS+ uses a shared secret key (known to both the client and server)
    to obfuscate the body of sent packets.  Only the packet body (not
    the header) is obfuscated.

    https://datatracker.ietf.org/doc/draft-ietf-opsawg-tacacs/?include_text=1#section-3.7

    ENCRYPTED {data} == data ^ pseudo_pad

    The pad is generated by concatenating a series of MD5 hashes (each 16
    bytes long) and truncating it to the length of the input data.

    pseudo_pad = {MD5_1 [,MD5_2 [ ... ,MD5_n]]} truncated to len(data)

    The first MD5 hash is generated by concatenating the session_id, the
    secret key, the version number and the sequence number and then
    running MD5 over that stream.  All of those input values are
    available in the packet header, except for the secret key which is a
    shared secret between the TACACS+ client and server.

    Subsequent hashes are generated by using the same input stream, but
    concatenating the previous hash value at the end of the input stream.

    MD5_1 = MD5{session_id, key, version, seq_no} MD5_2 = MD5{session_id,
    key, version, seq_no, MD5_1} ....  MD5_n = MD5{session_id, key,
    version, seq_no, MD5_n-1}

    :param header:     a TACACSHeader object
    :param body_bytes: packed bytes, i.e., `struct.pack(...)`
    :param secret:     a key used to encrypt/obfuscate packets according
                       to the TACACS+ spec

    :return:           packed bytes, i.e., `struct.pack(...)` representing the
                       obfuscated packet body
    """  # noqa

    # B = unsigned char
    # !I = network-order (big-endian) unsigned int
    body_length = len(body_bytes)
    unhashed = (
        struct.pack('!I', header.session_id) +
        six.b(secret) +
        struct.pack('B', header.version) +
        struct.pack('B', header.seq_no)
    )
    pad = hashed = md5(unhashed).digest()

    if (len(pad) < body_length):
        # remake hash, appending it to pad until pad >= header.length
        while True:
            hashed = md5(unhashed + hashed).digest()
            pad += hashed
            if len(pad) >= body_length:
                break

    pad = pad[0:(body_length)]
    pad = list(struct.unpack('B' * len(pad), pad))

    packet_body = []
    for x in struct.unpack('B' * body_length, body_bytes):
        packet_body.append(x ^ pad.pop(0))

    return struct.pack('B' * len(packet_body), *packet_body)


class TACACSPacket(object):

    def __init__(self, header, body_bytes, secret):
        """
        :param header:     a TACACSHeader object
        :param body_bytes: packed bytes, i.e., `struct.pack(...)`
        :param secret:     a key used to encrypt/obfuscate packets according
                           to the TACACS+ spec
        """
        self.header = header
        self.body_bytes = body_bytes
        self.secret = secret

    @property
    def encrypted(self):
        return self.secret is not None

    @property
    def seq_no(self):
        return self.header.seq_no

    @property
    def body(self):
        if self.encrypted:
            return self.crypt
        return self.body_bytes

    def __str__(self):
        return self.header.packed + self.body

    def __bytes__(self):
        return self.header.packed + self.body

    @property
    def crypt(self):
        return crypt(self.header, self.body_bytes, self.secret)


class TACACSHeader(object):

    def __init__(self, version, type, session_id, length, seq_no=1, flags=0):
        self.version = version
        self.type = type
        self.session_id = session_id
        self.length = length
        self.seq_no = seq_no
        self.flags = flags

    @property
    def version_max(self):
        return self.version // 0x10

    @property
    def version_min(self):
        return self.version % 0x10

    @property
    def packed(self):
        # All TACACS+ packets always begin with the following 12 byte header.
        # The header is always cleartext and describes the remainder of the
        # packet:
        # 1 2 3 4 5 6 7 8  1 2 3 4 5 6 7 8  1 2 3 4 5 6 7 8  1 2 3 4 5 6 7 8
        #
        # +----------------+----------------+----------------+----------------+
        # |major  | minor  |                |                |                |
        # |version| version|      type      |     seq_no     |   flags        |
        # +----------------+----------------+----------------+----------------+
        # |                            session_id                             |
        # +----------------+----------------+----------------+----------------+
        # |                              length                               |
        # +----------------+----------------+----------------+----------------+

        # B = unsigned char
        # !I = network-order (big-endian) unsigned int
        return struct.pack(
            'BBBB',
            self.version,
            self.type,
            self.seq_no,
            self.flags
        ) + struct.pack('!I', self.session_id) + struct.pack('!I', self.length)

    @classmethod
    def unpacked(cls, raw):
        # B = unsigned char
        # !I = network-order (big-endian) unsigned int
        raw = six.BytesIO(raw)
        raw_chars = raw.read(4)
        if raw_chars:
            version, type, seq_no, flags = struct.unpack(
                'BBBB',
                raw_chars
            )
            session_id, length = struct.unpack('!II', raw.read(8))
            return cls(version, type, session_id, length, seq_no, flags)
        else:
            raise ValueError(
                "Unable to extract data from header. Likely the TACACS+ key does not match between server and client"
            )

    def __str__(self):
        return ', '.join([
            'version: %s' % self.version,
            'type: %s' % self.type,
            'session_id: %s' % self.session_id,
            'length: %s' % self.length,
            'seq_no: %s' % self.seq_no,
            'flags: %s' % self.flags,
        ])
