using System;
using System.Collections;
using UnityEngine.Networking;

namespace Vrar.Telemetry
{
    /// <summary>Where frames come from. Swapped for a replay source in tests.</summary>
    public interface ITelemetrySource
    {
        IEnumerator Fetch(int requestToken, Action<TelemetryFrame, string> onComplete);
        void CancelAll();
    }

    /// <summary>Polls the FastAPI service with <c>UnityWebRequest</c>.</summary>
    public sealed class HttpTelemetrySource : ITelemetrySource
    {
        private readonly string _endpoint;
        private readonly int _timeoutSeconds;
        private readonly bool _followServerClock;
        private readonly string _turbineId;

        public HttpTelemetrySource(
            string endpoint,
            int timeoutSeconds = 3,
            bool followServerClock = false,
            string turbineId = null)
        {
            _endpoint = (endpoint ?? string.Empty).TrimEnd('/');
            _timeoutSeconds = timeoutSeconds;
            _followServerClock = followServerClock;
            _turbineId = turbineId;
        }

        public string Endpoint => _endpoint;
        public bool FollowServerClock => _followServerClock;
        public string TurbineId => _turbineId;

        /// <summary>
        /// URL for one frame. In follow mode the session clock decides the moment,
        /// so <c>t</c> is omitted; otherwise the caller's token is the timestamp.
        /// An optional turbine id is appended so the request is explicit about
        /// which machine it is for.
        /// </summary>
        public static string TelemetryUrl(
            string endpoint, int requestToken, bool followServerClock, string turbineId = null)
        {
            string root = (endpoint ?? string.Empty).TrimEnd('/');
            string query = followServerClock ? string.Empty : $"?t={requestToken / 1f:0.0}";

            if (!string.IsNullOrEmpty(turbineId))
            {
                string separator = query.Length == 0 ? "?" : "&";
                query += $"{separator}turbine_id={UnityWebRequest.EscapeURL(turbineId)}";
            }

            return $"{root}/api/telemetry{query}";
        }

        public IEnumerator Fetch(int requestToken, Action<TelemetryFrame, string> onComplete)
        {
            string url = TelemetryUrl(_endpoint, requestToken, _followServerClock, _turbineId);
            using UnityWebRequest request = UnityWebRequest.Get(url);
            request.timeout = _timeoutSeconds;
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                onComplete?.Invoke(null, request.error ?? "request failed");
                yield break;
            }

            TelemetryFrame frame;
            try
            {
                frame = UnityEngine.JsonUtility.FromJson<TelemetryFrame>(request.downloadHandler.text);
            }
            catch (Exception exception)
            {
                onComplete?.Invoke(null, $"invalid payload: {exception.Message}");
                yield break;
            }

            if (frame?.components == null)
            {
                onComplete?.Invoke(null, "payload contained no components");
                yield break;
            }

            onComplete?.Invoke(frame, null);
        }

        public void CancelAll()
        {
        }
    }

    /// <summary>
    /// Replays a fixed list of frames. Used by the PlayMode tests and by the
    /// offline demo mode (<c>-vrar-sample</c>) when no service is running.
    /// </summary>
    public sealed class ReplayTelemetrySource : ITelemetrySource
    {
        private readonly TelemetryFrame[] _frames;
        private int _cursor;

        public ReplayTelemetrySource(TelemetryFrame[] frames)
        {
            _frames = frames ?? Array.Empty<TelemetryFrame>();
        }

        public int Cursor => _cursor;

        public IEnumerator Fetch(int requestToken, Action<TelemetryFrame, string> onComplete)
        {
            if (_frames.Length == 0)
            {
                onComplete?.Invoke(null, "no frames available");
                yield break;
            }

            onComplete(_frames[_cursor % _frames.Length], null);
            _cursor++;
            yield return null;
        }

        public void CancelAll()
        {
            _cursor = 0;
        }
    }
}