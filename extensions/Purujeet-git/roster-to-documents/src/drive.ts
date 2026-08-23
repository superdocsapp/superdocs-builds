function saveDocumentToDrive(blob: any, preferredFileName: string): any {
  var folderId = getScriptProperty(CONFIG.OUTPUT_FOLDER_PROPERTY);
  if (folderId) {
    return DriveApp.getFolderById(folderId).createFile(blob.setName(preferredFileName));
  }
  return DriveApp.createFile(blob.setName(preferredFileName));
}
