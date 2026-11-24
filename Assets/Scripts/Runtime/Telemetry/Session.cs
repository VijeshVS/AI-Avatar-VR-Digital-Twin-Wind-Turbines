using System;

namespace Vrar.Telemetry
{
    /// <summary>
    /// Plain-old-data mirror of <c>GET /api/session</c>. Field names match the
    /// Python service exactly, so <see cref="UnityEngine.JsonUtility"/> needs no
    /// converter.
    /// </summary>
    [Serializable]
    public class SessionPayload
    {
        public string scenario;
        public float t;
        public bool playing;
        public float speed;
        public string focus;
        public int focus_seq;
    }

    /// <summary>
    /// Consumes the web console's focus command exactly once per sequence number.
    ///
    /// Applying <c>focus</c> on every poll would fight the viewer: the camera
    /// would be dragged back to the component every second, so WASD could never
    /// fly away. The service increments <c>focus_seq</c> only when the focus
    /// actually changes, which is the signal this class follows.
    /// </summary>
    public sealed class SessionFocusFollower
    {
        private int _lastSequence = -1;

        public int LastSequence => _lastSequence;

        /// <summary>
        /// True when this poll carries a focus command that has not been applied.
        /// </summary>
        public bool TryConsume(SessionPayload session, out string componentId, out bool clearFocus)
        {
            componentId = null;
            clearFocus = false;

            if (session == null || session.focus_seq == _lastSequence)
            {
                return false;
            }

            _lastSequence = session.focus_seq;

            if (string.IsNullOrEmpty(session.focus))
            {
                clearFocus = true;
                return true;
            }

            componentId = session.focus;
            return true;
        }

        public void Reset()
        {
            _lastSequence = -1;
        }
    }
}
