class ExportResult {
  final List<int> fileBytes;
  final String filename;
  final String contentType;

  ExportResult({
    required this.fileBytes,
    required this.filename,
    required this.contentType,
  });
}
