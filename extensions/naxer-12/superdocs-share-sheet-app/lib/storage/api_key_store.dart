import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiKeyStore {
  static const String _keyName = 'superdocs_api_key';
  final FlutterSecureStorage _storage;

  ApiKeyStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<void> saveApiKey(String apiKey) async {
    try {
      await _storage.write(key: _keyName, value: apiKey);
    } catch (_) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_keyName, apiKey);
    }
  }

  Future<String?> getApiKey() async {
    try {
      final value = await _storage.read(key: _keyName);
      if (value != null && value.isNotEmpty) return value;
    } catch (_) {}

    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyName);
  }

  Future<void> clearApiKey() async {
    try {
      await _storage.delete(key: _keyName);
    } catch (_) {}

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyName);
  }
}
