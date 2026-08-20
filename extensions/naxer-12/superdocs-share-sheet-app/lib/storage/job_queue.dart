import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/edit_job.dart';

class JobQueue {
  static const String _queueKey = 'superdocs_job_queue';

  Future<List<EditJob>> getJobs() async {
    final prefs = await SharedPreferences.getInstance();
    final rawList = prefs.getStringList(_queueKey) ?? [];
    return rawList
        .map((item) {
          try {
            return EditJob.fromJson(jsonDecode(item) as Map<String, dynamic>);
          } catch (_) {
            return null;
          }
        })
        .whereType<EditJob>()
        .toList();
  }

  Future<void> addJob(EditJob job) async {
    final jobs = await getJobs();
    jobs.removeWhere((j) => j.jobId == job.jobId);
    jobs.insert(0, job);
    await _saveJobs(jobs);
  }

  Future<void> updateJobStatus(String jobId, String status, {String? updatedHtml}) async {
    final jobs = await getJobs();
    final index = jobs.indexWhere((j) => j.jobId == jobId);
    if (index != -1) {
      jobs[index] = jobs[index].copyWith(
        status: status,
        updatedHtml: updatedHtml ?? jobs[index].updatedHtml,
      );
      await _saveJobs(jobs);
    }
  }

  Future<void> removeJob(String jobId) async {
    final jobs = await getJobs();
    jobs.removeWhere((j) => j.jobId == jobId);
    await _saveJobs(jobs);
  }

  Future<void> _saveJobs(List<EditJob> jobs) async {
    final prefs = await SharedPreferences.getInstance();
    final stringList = jobs.map((j) => jsonEncode(j.toJson())).toList();
    await prefs.setStringList(_queueKey, stringList);
  }
}
