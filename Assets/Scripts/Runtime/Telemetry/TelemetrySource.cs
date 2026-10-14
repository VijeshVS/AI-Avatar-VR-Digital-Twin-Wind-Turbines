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

        public HttpTelemetrySource(string endpoint, int timeoutSeconds = 3)
        {
            _endpoint = endpoint;
            _timeoutSeconds = timeoutSeconds;
        }

        public string Endpoint => _endpoint;

        public IEnumerator Fetch(int requestToken, Action<TelemetryFrame, string> onComplete)
        {
            string url = $"{_endpoint}/api/telemetry?t={requestToken / 10f:0.0}";
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