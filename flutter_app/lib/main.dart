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
      title: 'Plugs Outreach Assistant',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF2563EB),
        useMaterial3: true,
      ),
      home: const OutreachChatScreen(),
    );
  }
}

enum Sender {
  bot,
  user,
}

class ChatMessage {
  final Sender sender;
  final String text;
  final DateTime time;

  ChatMessage({
    required this.sender,
    required this.text,
    DateTime? time,
  }) : time = time ?? DateTime.now();
}

class OutreachChatScreen extends StatefulWidget {
  const OutreachChatScreen({super.key});

  @override
  State<OutreachChatScreen> createState() => _OutreachChatScreenState();
}

class _OutreachChatScreenState extends State<OutreachChatScreen> {
  static const backendUrl = 'http://127.0.0.1:8000';

  final inputController = TextEditingController();
  final messageTemplateController = TextEditingController();
  final scrollController = ScrollController();

  final List<ChatMessage> messages = [];

  Timer? pollTimer;

  bool backendReady = false;
  bool linkedInConnected = false;
  bool loading = false;
  bool outreachRunning = false;
  bool likePostAfterInvite = false;

  String backendStatus = 'checking';
  String? campaignId;
  String? searchUrl;

  int dailyLimit = 10;

  Map<String, dynamic> stats = {
    'sent': 0,
    'accepted': 0,
    'failed': 0,
    'alreadyConnected': 0,
    'messagesSent': 0,
    'sentToday': 0,
    'postsLiked': 0,
  };

  List<dynamic> previewPeople = [];

  final Set<String> shownLogKeys = {};

  @override
  void initState() {
    super.initState();

    messageTemplateController.text = 'Hi {{first_name}}, thanks for connecting.';

    bot('Hi, I am Plugs Outreach Assistant.');
    bot('I will help you connect LinkedIn, preview people, send limited invitations, track accepted connections, like one recent post if enabled, and send first messages.');
    bot('First, I will check if the backend is running.');

    checkBackend();

    pollTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      refreshProgress();
      refreshLogs();
      refreshStats();
    });
  }

  @override
  void dispose() {
    pollTimer?.cancel();
    inputController.dispose();
    messageTemplateController.dispose();
    scrollController.dispose();
    super.dispose();
  }

  void bot(String text) {
    setState(() {
      messages.add(ChatMessage(sender: Sender.bot, text: text));
    });

    scrollToBottom();
  }

  void user(String text) {
    setState(() {
      messages.add(ChatMessage(sender: Sender.user, text: text));
    });

    scrollToBottom();
  }

  void scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!scrollController.hasClients) return;

      scrollController.animateTo(
        scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> checkBackend() async {
    setState(() {
      loading = true;
    });

    try {
      final response = await http.get(Uri.parse('$backendUrl/health'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);

        setState(() {
          backendReady = true;
          backendStatus = data['status'] ?? 'idle';
        });

        bot('Backend is connected.');
        await checkLinkedInStatus();
      } else {
        setState(() {
          backendReady = false;
          backendStatus = 'error';
        });

        bot('Backend returned error ${response.statusCode}. Start the launcher/backend first.');
      }
    } catch (_) {
      setState(() {
        backendReady = false;
        backendStatus = 'not running';
      });

      bot('Backend is not running. Please start the launcher first.');
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> checkLinkedInStatus() async {
    if (!backendReady) return;

    try {
      final response = await http.get(Uri.parse('$backendUrl/linkedin/status'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);

        setState(() {
          linkedInConnected = data['connected'] == true;
        });

        if (linkedInConnected) {
          bot('LinkedIn is already connected.');
          bot('Paste a LinkedIn people-search URL to create a campaign.');
        } else {
          bot('LinkedIn is not connected yet. Click "Connect LinkedIn" to log in through LinkedIn directly.');
        }
      } else {
        bot('Could not check LinkedIn status.');
      }
    } catch (error) {
      bot('LinkedIn status check failed: $error');
    }
  }

  Future<void> connectLinkedIn() async {
    if (!backendReady) {
      bot('Backend is not ready yet.');
      return;
    }

    setState(() {
      loading = true;
    });

    user('Connect LinkedIn');
    bot('Opening LinkedIn login in browser. Please log in there. I will wait for login to complete.');

    try {
      final response = await http.post(
        Uri.parse('$backendUrl/linkedin/connect'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'timeout_seconds': 300,
        }),
      );

      final data = jsonDecode(response.body);

      setState(() {
        linkedInConnected = data['connected'] == true;
      });

      if (linkedInConnected) {
        bot('LinkedIn connected successfully.');
        bot('Now paste a LinkedIn people-search URL.');
      } else {
        bot(data['message'] ?? 'LinkedIn login failed or timed out.');
      }
    } catch (error) {
      bot('LinkedIn connection failed: $error');
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> createCampaignAndPreview() async {
    final url = inputController.text.trim();

    if (url.isEmpty) {
      bot('Paste a LinkedIn people-search URL first.');
      return;
    }

    if (!url.startsWith('https://www.linkedin.com/')) {
      bot('Please paste a valid LinkedIn URL.');
      return;
    }

    setState(() {
      loading = true;
      searchUrl = url;
      previewPeople = [];
    });

    user(url);
    inputController.clear();

    bot('Creating outreach campaign...');
    bot('Daily invitation limit is set to $dailyLimit.');
    bot(likePostAfterInvite
        ? 'Post-like after invite is enabled.'
        : 'Post-like after invite is disabled.');

    try {
      final createResponse = await http.post(
        Uri.parse('$backendUrl/campaigns'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'name': 'LinkedIn Outreach Campaign',
          'search_url': url,
          'daily_limit': dailyLimit,
          'message_template': messageTemplateController.text.trim(),
          'like_post_after_invite': likePostAfterInvite,
        }),
      );

      if (createResponse.statusCode != 200) {
        bot('Could not create campaign: ${createResponse.body}');
        return;
      }

      final createData = jsonDecode(createResponse.body);
      campaignId = createData['campaignId'];

      bot('Campaign created.');
      bot('Previewing people from the search URL...');

      final previewResponse = await http.post(
        Uri.parse('$backendUrl/campaigns/preview'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'campaign_id': campaignId,
          'search_url': url,
          'limit': 25,
        }),
      );

      if (previewResponse.statusCode != 200) {
        bot('Could not preview people: ${previewResponse.body}');
        return;
      }

      final previewData = jsonDecode(previewResponse.body);

      setState(() {
        previewPeople = previewData['people'] ?? [];
      });

      bot('I found ${previewPeople.length} people.');
      if (previewPeople.isNotEmpty) {
        bot('Review the preview list on the right, then click "Start Outreach" when ready.');
      } else {
        bot('No people were found. Try another LinkedIn people-search URL.');
      }
    } catch (error) {
      bot('Campaign preview failed: $error');
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> startOutreach() async {
    if (campaignId == null || searchUrl == null) {
      bot('Create and preview a campaign first.');
      return;
    }

    setState(() {
      loading = true;
    });

    user('Start Outreach');
    bot('Starting outreach. I will send at most $dailyLimit invitations today.');

    try {
      final response = await http.post(
        Uri.parse('$backendUrl/campaigns/start'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'campaign_id': campaignId,
          'search_url': searchUrl,
          'daily_limit': dailyLimit,
        }),
      );

      if (response.statusCode == 200) {
        setState(() {
          outreachRunning = true;
        });

        bot('Outreach started. I will show progress in the chat and stats panel.');
      } else {
        bot('Could not start outreach: ${response.body}');
      }
    } catch (error) {
      bot('Start outreach failed: $error');
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> stopOutreach() async {
    user('Stop Outreach');

    try {
      await http.post(Uri.parse('$backendUrl/campaigns/stop'));

      setState(() {
        outreachRunning = false;
      });

      bot('Stop requested.');
    } catch (error) {
      bot('Stop failed: $error');
    }
  }

  Future<void> checkAccepted() async {
    if (campaignId == null) {
      bot('Create a campaign first.');
      return;
    }

    setState(() {
      loading = true;
    });

    user('Check Accepted Connections');
    bot('Checking which invited people accepted your connection request.');

    try {
      final response = await http.post(
        Uri.parse('$backendUrl/campaigns/check-accepted'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'campaign_id': campaignId,
          'limit': 50,
        }),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        bot('Checked ${data['checked']} profiles. Accepted: ${data['accepted']}.');
      } else {
        bot('Could not check accepted connections: ${response.body}');
      }
    } catch (error) {
      bot('Check accepted failed: $error');
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> sendFirstMessage() async {
    if (campaignId == null) {
      bot('Create a campaign first.');
      return;
    }

    final template = messageTemplateController.text.trim();

    if (template.isEmpty) {
      bot('Enter a message after accepted invitation first.');
      return;
    }

    setState(() {
      loading = true;
    });

    user('Send first message to accepted connections');
    bot('Sending first message to accepted connections.');

    try {
      final response = await http.post(
        Uri.parse('$backendUrl/campaigns/send-message'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'campaign_id': campaignId,
          'message_template': template,
          'confirm_send': true,
          'limit': 10,
        }),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        bot('Messages sent: ${data['sent']}. Failed: ${data['failed']}.');
      } else {
        bot('Could not send messages: ${response.body}');
      }
    } catch (error) {
      bot('Send message failed: $error');
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> refreshProgress() async {
    if (!backendReady) return;

    try {
      final response = await http.get(Uri.parse('$backendUrl/progress'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final currentState = data['state'] ?? {};

        setState(() {
          backendStatus = currentState['status'] ?? backendStatus;
          outreachRunning = data['running'] == true;
        });
      }
    } catch (_) {}
  }

  Future<void> refreshLogs() async {
    if (!backendReady) return;

    try {
      final response = await http.get(Uri.parse('$backendUrl/logs'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final logs = data['logs'] ?? [];

        for (final log in logs) {
          final key = '${log['time']}|${log['message']}';

          if (shownLogKeys.contains(key)) continue;

          shownLogKeys.add(key);

          final text = log['message']?.toString() ?? '';
          if (text.trim().isNotEmpty) {
            bot(text);
          }
        }
      }
    } catch (_) {}
  }

  Future<void> refreshStats() async {
    if (campaignId == null) return;

    try {
      final response = await http.get(Uri.parse('$backendUrl/campaigns/$campaignId/stats'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);

        setState(() {
          stats = data['stats'] ?? stats;
        });
      }
    } catch (_) {}
  }

  void handleInputSubmit() {
    final text = inputController.text.trim();

    if (text.isEmpty) return;

    if (text.startsWith('https://www.linkedin.com/')) {
      createCampaignAndPreview();
      return;
    }

    user(text);
    inputController.clear();

    bot('I received your message. For now, paste a LinkedIn people-search URL or use the action buttons.');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      appBar: AppBar(
        title: const Text('Plugs Outreach Assistant'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: Text(
                'Backend: $backendStatus',
                style: const TextStyle(fontSize: 13),
              ),
            ),
          ),
        ],
      ),
      body: Row(
        children: [
          Expanded(
            flex: 3,
            child: Column(
              children: [
                Expanded(
                  child: ListView.builder(
                    controller: scrollController,
                    padding: const EdgeInsets.all(20),
                    itemCount: messages.length,
                    itemBuilder: (context, index) {
                      return ChatBubble(message: messages[index]);
                    },
                  ),
                ),
                ActionBar(
                  loading: loading,
                  backendReady: backendReady,
                  linkedInConnected: linkedInConnected,
                  outreachRunning: outreachRunning,
                  hasCampaign: campaignId != null,
                  onCheckBackend: checkBackend,
                  onConnectLinkedIn: connectLinkedIn,
                  onStartOutreach: startOutreach,
                  onStopOutreach: stopOutreach,
                  onCheckAccepted: checkAccepted,
                  onSendFirstMessage: sendFirstMessage,
                ),
                InputComposer(
                  controller: inputController,
                  loading: loading,
                  onSubmit: handleInputSubmit,
                ),
              ],
            ),
          ),
          SidePanel(
            linkedInConnected: linkedInConnected,
            dailyLimit: dailyLimit,
            onDailyLimitChanged: (value) {
              setState(() {
                dailyLimit = value;
              });
            },
            messageTemplateController: messageTemplateController,
            likePostAfterInvite: likePostAfterInvite,
            onLikePostAfterInviteChanged: (value) {
              setState(() {
                likePostAfterInvite = value;
              });
            },
            stats: stats,
            previewPeople: previewPeople,
          ),
        ],
      ),
    );
  }
}

class ChatBubble extends StatelessWidget {
  final ChatMessage message;

  const ChatBubble({
    super.key,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    final isUser = message.sender == Sender.user;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 720),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFF2563EB) : Colors.white,
          borderRadius: BorderRadius.circular(8),
          border: isUser ? null : Border.all(color: const Color(0xFFE2E8F0)),
          boxShadow: [
            if (!isUser)
              BoxShadow(
                color: Colors.black.withOpacity(0.04),
                blurRadius: 10,
                offset: const Offset(0, 4),
              ),
          ],
        ),
        child: Text(
          message.text,
          style: TextStyle(
            color: isUser ? Colors.white : const Color(0xFF0F172A),
            height: 1.35,
          ),
        ),
      ),
    );
  }
}

class ActionBar extends StatelessWidget {
  final bool loading;
  final bool backendReady;
  final bool linkedInConnected;
  final bool outreachRunning;
  final bool hasCampaign;

  final VoidCallback onCheckBackend;
  final VoidCallback onConnectLinkedIn;
  final VoidCallback onStartOutreach;
  final VoidCallback onStopOutreach;
  final VoidCallback onCheckAccepted;
  final VoidCallback onSendFirstMessage;

  const ActionBar({
    super.key,
    required this.loading,
    required this.backendReady,
    required this.linkedInConnected,
    required this.outreachRunning,
    required this.hasCampaign,
    required this.onCheckBackend,
    required this.onConnectLinkedIn,
    required this.onStartOutreach,
    required this.onStopOutreach,
    required this.onCheckAccepted,
    required this.onSendFirstMessage,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(
          top: BorderSide(color: Color(0xFFE2E8F0)),
        ),
      ),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          OutlinedButton(
            onPressed: loading ? null : onCheckBackend,
            child: const Text('Check Backend'),
          ),
          FilledButton(
            onPressed: loading || !backendReady || linkedInConnected ? null : onConnectLinkedIn,
            child: const Text('Connect LinkedIn'),
          ),
          FilledButton.tonal(
            onPressed: loading || !backendReady || !linkedInConnected || !hasCampaign || outreachRunning
                ? null
                : onStartOutreach,
            child: const Text('Start Outreach'),
          ),
          OutlinedButton(
            onPressed: loading || !outreachRunning ? null : onStopOutreach,
            child: const Text('Stop'),
          ),
          OutlinedButton(
            onPressed: loading || !hasCampaign ? null : onCheckAccepted,
            child: const Text('Check Accepted'),
          ),
          OutlinedButton(
            onPressed: loading || !hasCampaign ? null : onSendFirstMessage,
            child: const Text('Send First Message'),
          ),
        ],
      ),
    );
  }
}

class InputComposer extends StatelessWidget {
  final TextEditingController controller;
  final bool loading;
  final VoidCallback onSubmit;

  const InputComposer({
    super.key,
    required this.controller,
    required this.loading,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
      color: Colors.white,
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: controller,
              enabled: !loading,
              minLines: 1,
              maxLines: 4,
              decoration: const InputDecoration(
                hintText: 'Paste LinkedIn people-search URL...',
                border: OutlineInputBorder(),
              ),
              onSubmitted: (_) => onSubmit(),
            ),
          ),
          const SizedBox(width: 12),
          FilledButton(
            onPressed: loading ? null : onSubmit,
            child: const Text('Send'),
          ),
        ],
      ),
    );
  }
}

class SidePanel extends StatelessWidget {
  final bool linkedInConnected;
  final int dailyLimit;
  final ValueChanged<int> onDailyLimitChanged;
  final TextEditingController messageTemplateController;
  final bool likePostAfterInvite;
  final ValueChanged<bool> onLikePostAfterInviteChanged;
  final Map<String, dynamic> stats;
  final List<dynamic> previewPeople;

  const SidePanel({
    super.key,
    required this.linkedInConnected,
    required this.dailyLimit,
    required this.onDailyLimitChanged,
    required this.messageTemplateController,
    required this.likePostAfterInvite,
    required this.onLikePostAfterInviteChanged,
    required this.stats,
    required this.previewPeople,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 380,
      height: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(
          left: BorderSide(color: Color(0xFFE2E8F0)),
        ),
      ),
      child: ListView(
        children: [
          const Text(
            'Campaign Control',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 16),
          StatusTile(
            label: 'LinkedIn',
            value: linkedInConnected ? 'Connected' : 'Not connected',
            good: linkedInConnected,
          ),
          const SizedBox(height: 16),
          const Text(
            'Daily Invite Limit',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          Slider(
            value: dailyLimit.toDouble(),
            min: 1,
            max: 10,
            divisions: 9,
            label: dailyLimit.toString(),
            onChanged: (value) => onDailyLimitChanged(value.round()),
          ),
          Text('$dailyLimit invitations/day'),
          const SizedBox(height: 20),
          const Text(
            'Message After Accepted Invitation',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: messageTemplateController,
            minLines: 3,
            maxLines: 5,
            decoration: const InputDecoration(
              hintText: 'Hi {{first_name}}, thanks for connecting.',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'Like one recent post after invite',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            subtitle: const Text('Runs only for invited profiles, within the daily limit.'),
            value: likePostAfterInvite,
            onChanged: onLikePostAfterInviteChanged,
          ),
          const SizedBox(height: 24),
          const Text(
            'Stats',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 8),
          StatRow(label: 'Sent', value: stats['sent'] ?? 0),
          StatRow(label: 'Accepted', value: stats['accepted'] ?? 0),
          StatRow(label: 'Failed', value: stats['failed'] ?? 0),
          StatRow(label: 'Already connected', value: stats['alreadyConnected'] ?? 0),
          StatRow(label: 'Messages sent', value: stats['messagesSent'] ?? 0),
          StatRow(label: 'Sent today', value: stats['sentToday'] ?? 0),
          StatRow(label: 'Posts liked', value: stats['postsLiked'] ?? 0),
          const SizedBox(height: 24),
          const Text(
            'Preview People',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 8),
          if (previewPeople.isEmpty)
            const Text(
              'Paste a LinkedIn people-search URL to preview profiles.',
              style: TextStyle(color: Color(0xFF64748B)),
            )
          else
            ...previewPeople.take(10).map((person) {
              return PersonPreviewCard(person: person);
            }),
        ],
      ),
    );
  }
}

class StatusTile extends StatelessWidget {
  final String label;
  final String value;
  final bool good;

  const StatusTile({
    super.key,
    required this.label,
    required this.value,
    required this.good,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: good ? const Color(0xFFECFDF5) : const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: good ? const Color(0xFF86EFAC) : const Color(0xFFFED7AA),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          Text(value),
        ],
      ),
    );
  }
}

class StatRow extends StatelessWidget {
  final String label;
  final dynamic value;

  const StatRow({
    super.key,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          Text(
            value.toString(),
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

class PersonPreviewCard extends StatelessWidget {
  final dynamic person;

  const PersonPreviewCard({
    super.key,
    required this.person,
  });

  @override
  Widget build(BuildContext context) {
    final name = person['name']?.toString() ?? 'Unknown';
    final headline = person['headline']?.toString() ?? '';
    final location = person['location']?.toString() ?? '';
    final canConnect = person['canConnect'] == true;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: const Color(0xFFE2E8F0)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            name,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          if (headline.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              headline,
              style: const TextStyle(fontSize: 13),
            ),
          ],
          if (location.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              location,
              style: const TextStyle(
                fontSize: 12,
                color: Color(0xFF64748B),
              ),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            canConnect ? 'Connect available' : 'Connect not visible',
            style: TextStyle(
              fontSize: 12,
              color: canConnect ? const Color(0xFF15803D) : const Color(0xFFB45309),
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}