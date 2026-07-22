import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(const PlugsApp());
}

class PlugsApp extends StatelessWidget {
  const PlugsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Plugs',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: Colors.blue,
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  static const backendUrl = 'http://127.0.0.1:8000';

  final jobTitleController = TextEditingController();
  final locationController = TextEditingController();

  String status = 'Checking backend...';
  String message = '';
  bool backendReady = false;
  bool running = false;
  List<dynamic> logs = [];

  Timer? timer;

  @override
  void initState() {
    super.initState();
    checkBackend();

    timer = Timer.periodic(const Duration(seconds: 2), (_) {
      refreshProgress();
      refreshLogs();
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    jobTitleController.dispose();
    locationController.dispose();
    super.dispose();
  }

  String buildLinkedInSearchUrl() {
    final jobTitle = jobTitleController.text.trim();
    final location = locationController.text.trim();

    final uri = Uri.https(
      'www.linkedin.com',
      '/jobs/search/',
      {
        'keywords': jobTitle,
        'location': location,
      },
    );

    return uri.toString();
  }

  Future<void> checkBackend() async {
    try {
      final response = await http.get(Uri.parse('$backendUrl/health'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);

        setState(() {
          backendReady = true;
          status = data['status'] ?? 'idle';
          message = 'Backend connected';
        });
      } else {
        setState(() {
          backendReady = false;
          status = 'Backend error';
          message = 'Backend returned ${response.statusCode}';
        });
      }
    } catch (_) {
      setState(() {
        backendReady = false;
        status = 'Backend not running';
        message = 'Start the launcher first';
      });
    }
  }

  Future<void> startScraper() async {
    final jobTitle = jobTitleController.text.trim();
    final location = locationController.text.trim();

    if (jobTitle.isEmpty || location.isEmpty) {
      setState(() {
        message = 'Enter both job role and location';
      });
      return;
    }

    final searchUrl = buildLinkedInSearchUrl();

    try {
      final response = await http.post(
        Uri.parse('$backendUrl/start'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'search_urls': [searchUrl],
        }),
      );

      if (response.statusCode == 200) {
        setState(() {
          running = true;
          status = 'running';
          message = 'Scraping started for $jobTitle in $location';
        });
      } else {
        setState(() {
          message = 'Could not start scraper: ${response.body}';
        });
      }
    } catch (error) {
      setState(() {
        message = 'Start failed: $error';
      });
    }
  }

  Future<void> stopScraper() async {
    try {
      await http.post(Uri.parse('$backendUrl/stop'));

      setState(() {
        running = false;
        status = 'stopping';
        message = 'Stopping scraper';
      });
    } catch (error) {
      setState(() {
        message = 'Stop failed: $error';
      });
    }
  }

  Future<void> refreshProgress() async {
    try {
      final response = await http.get(Uri.parse('$backendUrl/progress'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final state = data['state'] ?? {};

        setState(() {
          running = data['running'] == true;
          status = state['status'] ?? status;
        });
      }
    } catch (_) {}
  }

  Future<void> refreshLogs() async {
    try {
      final response = await http.get(Uri.parse('$backendUrl/logs'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);

        setState(() {
          logs = data['logs'] ?? [];
        });
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final canStart = backendReady && !running;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Plugs'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Backend status: $status'),
            const SizedBox(height: 8),
            Text(message),
            const SizedBox(height: 24),

            TextField(
              controller: jobTitleController,
              decoration: const InputDecoration(
                labelText: 'Job role',
                hintText: 'AI Engineer, Full Stack Developer, Data Analyst',
                border: OutlineInputBorder(),
              ),
              enabled: !running,
            ),

            const SizedBox(height: 16),

            TextField(
              controller: locationController,
              decoration: const InputDecoration(
                labelText: 'Location',
                hintText: 'India, Bengaluru, Remote, United States',
                border: OutlineInputBorder(),
              ),
              enabled: !running,
            ),

            const SizedBox(height: 20),

            Row(
              children: [
                FilledButton(
                  onPressed: canStart ? startScraper : null,
                  child: const Text('Start'),
                ),
                const SizedBox(width: 12),
                OutlinedButton(
                  onPressed: running ? stopScraper : null,
                  child: const Text('Stop'),
                ),
              ],
            ),

            const SizedBox(height: 24),

            const Text(
              'Logs',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),

            const SizedBox(height: 12),

            Expanded(
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                color: Colors.black87,
                child: ListView.builder(
                  itemCount: logs.length,
                  itemBuilder: (context, index) {
                    final log = logs[index];

                    return Text(
                      '[${log['time']}] ${log['message']}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontFamily: 'monospace',
                      ),
                    );
                  },
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}