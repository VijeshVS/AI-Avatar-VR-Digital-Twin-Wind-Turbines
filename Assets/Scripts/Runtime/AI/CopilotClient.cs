using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace Vrar.AI
{
    /// <summary>
    /// Wire models for <c>POST /api/assistant</c>. Field names match the Python
    /// service exactly so <see cref="JsonUtility"/> needs no converter.
    /// </summary>
    [Serializable]
    public class CopilotRequest
    {
        public string question;
        public float t;
        public string scenario;
    }

    [Serializable]
    public class CopilotReply
    {
        public string answer;
        public string source;
        public string detail;
        public CopilotAction[] actions;
    }

    /// <summary>
    /// One whitelisted action the copilot asked the client to perform. The
    /// service has already validated it; the panel still re-checks ids before use.
    /// </summary>
    [Serializable]
    public class CopilotAction
    {
        public string type;
        public string component_id;
        public string scenario;
        public float seconds;

        public const string FocusComponent = "focus_component";
        public const string SetScenario = "set_scenario";
        public const string SetTime = "set_time";
    }

    /// <summary>
    /// Posts one question to the grounded copilot and returns its answer plus
    /// actions. The model never computes numbers; the service builds the context.
    /// </summary>
    public sealed class CopilotClient
    {
        private readonly string _endpoint;
        private readonly int _timeoutSeconds;

        public CopilotClient(string endpoint, int timeoutSeconds = 20)
        {
            _endpoint = (endpoint ?? string.Empty).TrimEnd('/');
            _timeoutSeconds = Mathf.Max(1, timeoutSeconds);
        }

        public string Endpoint => _endpoint;

        public IEnumerator Ask(
            string question,
            float t,
            string scenario,
            Action<CopilotReply, string> onComplete)
        {
            var payload = new CopilotRequest
            {
                question = question ?? string.Empty,
                t = t,
                scenario = scenario ?? string.Empty,
            };
            byte[] body = Encoding.UTF8.GetBytes(JsonUtility.ToJson(payload));

            using var request = new UnityWebRequest($"{_endpoint}/api/assistant", "POST");
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = _timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                onComplete?.Invoke(null, request.error ?? "request failed");
                yield break;
            }

            CopilotReply reply;
            try
            {
                reply = JsonUtility.FromJson<CopilotReply>(request.downloadHandler.text);
            }
            catch (Exception exception)
            {
                onComplete?.Invoke(null, $"invalid payload: {exception.Message}");
                yield break;
            }

            if (reply == null || string.IsNullOrWhiteSpace(reply.answer))
            {
                onComplete?.Invoke(null, "payload contained no answer");
                yield break;
            }

            onComplete?.Invoke(reply, null);
        }
    }
}
