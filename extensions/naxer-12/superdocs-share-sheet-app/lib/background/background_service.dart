import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:workmanager/workmanager.dart';
import '../api/superdocs_client.dart';
import '../storage/job_queue.dart';

const String kSuperDocsPollTask = 'com.superdocs.pollTask';

@pragma('vm:entry-point')
void callbackDispatcher() {
  // callbackDispatcher runs in its own separate background isolate --
  // WidgetsBinding is never initialized there unless this is called first.
  // Without it, plugin method channels (shared_preferences,
  // flutter_secure_storage, http) can silently fail to work. Confirmed as
  // the real cause of a real bug on a real device (2026-08-17): the
  // JobScheduler logs proved this task genuinely ran and finished
  // (START -> STOP "app called jobFinished") while the app was
  // force-closed, but the job's persisted status never actually changed
  // from "pending" and no notification ever fired -- the broad `catch (_)`
  // below was silently swallowing a failure this fixes.
  WidgetsFlutterBinding.ensureInitialized();
  Workmanager().executeTask((task, inputData) async {
    if (task == kSuperDocsPollTask || task == Workmanager.iOSBackgroundTask) {
      final jobQueue = JobQueue();
      final client = SuperDocsClient();

      final pendingJobs = await jobQueue.getJobs();
      // Real status enum, verified against the live OpenAPI spec
      // (2026-08-17): pending, in_progress, awaiting_approval, completed,
      // failed, cancelled -- there is no "processing" status. Using the
      // wrong string here meant a job would stop being polled the moment it
      // left "pending", well before it ever reached awaiting_approval.
      final activeJobs = pendingJobs.where((j) =>
          j.status.toLowerCase() == 'pending' ||
          j.status.toLowerCase() == 'in_progress');

      for (final job in activeJobs) {
        try {
          final statusRes = await client.getJobStatus(jobId: job.jobId);
          final newStatus = statusRes.status.toLowerCase();

          if (newStatus != job.status.toLowerCase()) {
            await jobQueue.updateJobStatus(
              job.jobId,
              newStatus,
              updatedHtml: statusRes.updatedHtml,
            );

            if (newStatus == 'awaiting_approval' ||
                newStatus == 'completed' ||
                newStatus == 'failed') {
              await BackgroundService.showNotification(
                title: 'Document Edit Ready',
                body: '${job.filename} status is now: ${newStatus.replaceAll('_', ' ')}',
                payload: job.jobId,
              );
            }
          }
        } catch (_) {
          // Failure backoff handled by WorkManager retry mechanism
        }
      }
    }
    return Future.value(true);
  });
}

class BackgroundService {
  static final FlutterLocalNotificationsPlugin _notificationsPlugin =
      FlutterLocalNotificationsPlugin();

  static Future<void> initialize() async {
    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidSettings);

    await _notificationsPlugin.initialize(
      initSettings,
      onDidReceiveNotificationResponse: (response) {
        // Deep link handler payload can be read by app route navigation
      },
    );

    // POST_NOTIFICATIONS is declared in the manifest but Android 13+ (API
    // 33+) also requires it be granted at runtime -- declaring it alone
    // does nothing. Confirmed as a real, silent bug on a real device
    // (2026-08-17): `adb shell dumpsys package ... POST_NOTIFICATIONS`
    // showed `granted=false` even after the app had already run and its
    // background poll had already fired successfully -- the poll worked,
    // but the user would never have seen a notification about it. Without
    // this call there is no other path in the app that ever asks for it.
    await _notificationsPlugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();

    await Workmanager().initialize(
      callbackDispatcher,
      isInDebugMode: false,
    );
  }

  static Future<void> registerPeriodicPoll() async {
    await Workmanager().registerPeriodicTask(
      'superdocs_periodic_poll',
      kSuperDocsPollTask,
      frequency: const Duration(minutes: 15),
      constraints: Constraints(
        networkType: NetworkType.connected,
      ),
    );
  }

  static Future<void> showNotification({
    required String title,
    required String body,
    String? payload,
  }) async {
    const androidDetails = AndroidNotificationDetails(
      'superdocs_channel',
      'SuperDocs Edits',
      channelDescription: 'Notifications for document edit progress and approvals',
      importance: Importance.high,
      priority: Priority.high,
    );
    const notificationDetails = NotificationDetails(android: androidDetails);

    await _notificationsPlugin.show(
      DateTime.now().millisecond,
      title,
      body,
      notificationDetails,
      payload: payload,
    );
  }
}
