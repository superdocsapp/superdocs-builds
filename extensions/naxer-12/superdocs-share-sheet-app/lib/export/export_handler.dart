import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../api/superdocs_client.dart';
import '../models/export_result.dart';

class ExportHandler {
  final SuperDocsClient _client;

  ExportHandler({SuperDocsClient? client})
      : _client = client ?? SuperDocsClient();

  Future<void> exportAndShare({
    required String sessionId,
    required String filename,
    String format = 'docx',
  }) async {
    // 1. Request binary export from SuperDocs API
    final ExportResult exportResult = await _client.export(
      sessionId: sessionId,
      format: format,
    );

    // 2. Write file to temp directory
    final tempDir = await getTemporaryDirectory();
    final sanitizeFilename = filename.replaceAll(RegExp(r'[^\w\.-]'), '_');
    final finalFilename = sanitizeFilename.endsWith('.$format')
        ? sanitizeFilename
        : '$sanitizeFilename.$format';
    final filePath = '${tempDir.path}/$finalFilename';

    final file = File(filePath);
    await file.writeAsBytes(exportResult.fileBytes);

    // 3. Hand off to OS Share Sheet
    await Share.shareXFiles(
      [XFile(filePath, name: finalFilename, mimeType: exportResult.contentType)],
      text: 'Exported document from SuperDocs',
    );
  }
}
