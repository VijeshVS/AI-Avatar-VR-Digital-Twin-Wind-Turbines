using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Vrar.Telemetry
{
    /// <summary>Reader for the exported sample frames in StreamingAssets.</summary>
    public static class SampleFrames
    {
        [System.Serializable]
        private class SampleFile
        {
            public TelemetryFrame[] frames;
        }

        /// <summary>
        /// Load the frames written by <c>python -m telemetry.export_sample</c>.
        /// The PlayMode tests use this so the Unity DTOs are checked against a
        /// payload the Python service really produced.
        /// </summary>
        public static TelemetryFrame[] LoadFromStreamingAssets(string fileName)
        {
            string path = Path.Combine(Application.streamingAssetsPath, fileName);

            if (Application.platform == RuntimePlatform.Android)
            {
                using UnityEngine.Networking.UnityWebRequest request =
                    UnityEngine.Networking.UnityWebRequest.Get(Path.Combine("jar:file://", path));
                request.SendWebRequest();
                while (!request.isDone)
                {
                }

                return Parse(request.downloadHandler?.text);
            }

            if (!File.Exists(path))
            {
                Debug.LogWarning($"[VRAR] sample telemetry not found at {path}");
                return System.Array.Empty<TelemetryFrame>();
            }

            return Parse(File.ReadAllText(path));
        }

        public static TelemetryFrame[] Parse(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                return System.Array.Empty<TelemetryFrame>();
            }

            SampleFile file = JsonUtility.FromJson<SampleFile>(json);
            return file?.frames ?? System.Array.Empty<TelemetryFrame>();
        }

        /// <summary>Convenience for tests: parse from a raw JSON string.</summary>
        public static IReadOnlyList<TelemetryFrame> ParseFrames(string json) => Parse(json);
    }
}