/*
 * 与电脑端 cloud_relay.py / 手机端 RelayCrypto.kt 完全一致的云端加密实现。
 * - RFC 3526 group 14（2048 位 MODP，g = 2）模幂协商
 * - SHA-256 派生 AES-256 密钥
 * - AES-256-GCM，AAD = "class-schedule-relay-v1"
 * - 密文格式 base64(nonce[12] + ciphertext + tag)
 */
(function (root) {
  "use strict";

  const P = BigInt(
    "0x" +
      "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74" +
      "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14" +
      "374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406" +
      "B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A1" +
      "63BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356" +
      "208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E" +
      "462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2B" +
      "CBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FF" +
      "FFFFFFFFFFFFFF"
  );

  const AAD = new TextEncoder().encode("class-schedule-relay-v1");
  const MOD_BYTES = 256;

  function modPow(base, exp, mod) {
    let b = base % mod;
    let e = exp;
    let r = 1n;
    while (e > 0n) {
      if (e & 1n) r = (r * b) % mod;
      b = (b * b) % mod;
      e >>= 1n;
    }
    return r;
  }

  /** 32 字节随机私钥，最低位置 1（与 Kotlin 的 BigInteger(1, buf).or(ONE) 一致）。 */
  function randomPrivate() {
    const buf = new Uint8Array(32);
    root.crypto.getRandomValues(buf);
    let v = 0n;
    for (const byte of buf) v = (v << 8n) | BigInt(byte);
    return v | 1n;
  }

  /** 公钥按 Kotlin 的 toString(16) 输出，小写、无前导 0。 */
  function publicHex(priv) {
    return modPow(2n, priv, P).toString(16);
  }

  /** 共享值按 256 字节大端补齐，再做 SHA-256（对应 Python to_bytes(256, "big")）。 */
  function fixedBytes(value) {
    let hex = value.toString(16);
    if (hex.length > MOD_BYTES * 2) hex = hex.slice(-MOD_BYTES * 2);
    hex = hex.padStart(MOD_BYTES * 2, "0");
    const out = new Uint8Array(MOD_BYTES);
    for (let i = 0; i < MOD_BYTES; i += 1) {
      out[i] = parseInt(hex.substr(i * 2, 2), 16);
    }
    return out;
  }

  async function deriveKeyBytes(peerPub, priv) {
    const shared = modPow(peerPub, priv, P);
    return root.crypto.subtle.digest("SHA-256", fixedBytes(shared));
  }

  async function importKey(keyBytes) {
    return root.crypto.subtle.importKey(
      "raw", keyBytes, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]
    );
  }

  function b64(bytes) {
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return root.btoa(text);
  }

  function unb64(token) {
    const text = root.atob(token);
    const out = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i);
    return out;
  }

  async function encryptText(keyBytes, text) {
    const key = await importKey(keyBytes);
    const iv = root.crypto.getRandomValues(new Uint8Array(12));
    const body = new Uint8Array(
      await root.crypto.subtle.encrypt(
        { name: "AES-GCM", iv, additionalData: AAD, tagLength: 128 },
        key,
        new TextEncoder().encode(text)
      )
    );
    const raw = new Uint8Array(iv.length + body.length);
    raw.set(iv, 0);
    raw.set(body, iv.length);
    return b64(raw);
  }

  async function decryptText(keyBytes, token) {
    const raw = unb64(token);
    if (raw.length <= 12) throw new Error("密文长度异常");
    const key = await importKey(keyBytes);
    const plain = await root.crypto.subtle.decrypt(
      { name: "AES-GCM", iv: raw.slice(0, 12), additionalData: AAD, tagLength: 128 },
      key,
      raw.slice(12)
    );
    return new TextDecoder().decode(plain);
  }

  const RelayCrypto = {
    P,
    randomPrivate,
    publicHex,
    deriveKeyBytes,
    encryptText,
    decryptText
  };

  root.RelayCrypto = RelayCrypto;
  if (typeof module !== "undefined" && module.exports) module.exports = RelayCrypto;
})(typeof globalThis !== "undefined" ? globalThis : this);
