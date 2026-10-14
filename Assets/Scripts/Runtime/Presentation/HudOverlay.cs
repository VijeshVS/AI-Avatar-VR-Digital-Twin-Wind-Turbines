using System.Text;
using UnityEngine;
using Vrar.Health;
using Vrar.Turbine;

namespace Vrar.Presentation
{
    /// <summary>
    /// Immediate-mode plant readout: environment, connection state and one row
    /// per component with its health bar and the reason behind the score.
    /// Deliberately IMGUI: a PoC HUD with no assets and no UI scene wiring.
    /// </summary>
    public sealed class HudOverlay : MonoBehaviour
    {
        [SerializeField] private TurbineRig _rig;
        [SerializeField] private Telemetry.TelemetryFrame _lastFrame;
        [SerializeField] private bool _connected = true;
        [SerializeField] private string _statusLine = string.Empty;
        [SerializeField, Min(60f)] private float _width = 380f;
        [SerializeField, Min(12f)] private float _rowHeight = 44f;

        private GUIStyle _panel;
        private GUIStyle _title;
        private GUIStyle _body;
        private GUIStyle _caption;
        private readonly StringBuilder _builder = new StringBuilder();

        public void SetRig(TurbineRig rig)
        {
            _rig = rig;
        }

        public void SetFrame(Telemetry.TelemetryFrame frame, bool connected, string statusLine)
        {
            _lastFrame = frame;
            _connected = connected;
            _statusLine = statusLine;
        }

        private void OnGUI()
        {
            EnsureStyles();

            int rows = (_rig?.Avatars.Count ?? 0) + 4;
            float height = 96f + rows * _rowHeight;
            Rect panel = new Rect(16f, 16f, _width, height);

            GUI.Box(panel, GUIContent.none, _panel);
            GUI.Label(new Rect(panel.x + 14f, panel.y + 10f, _width - 28f, 22f), "WIND TURBINE DIGITAL TWIN — PoC", _title);
            GUI.Label(new Rect(panel.x + 14f, panel.y + 32f, _width - 28f, 20f), StatusText(), _body);

            float y = panel.y + 58f;
            y = DrawEnvironment(y, panel.width);
            y = DrawComponents(y, panel.width);
        }

        private string StatusText()
        {
            if (!_connected)
            {
                return _statusLine.Length > 0 ? $"OFFLINE — {_statusLine}" : "OFFLINE — waiting for telemetry";
            }

            _builder.Clear();
            _builder.Append(_statusLine);
            if (_lastFrame != null)
            {
                _builder.Append($"   t={_lastFrame.elapsed_s:0}s   scenario={_lastFrame.scenario}");
            }

            return _builder.ToString();
        }

        private float DrawEnvironment(float y, float width)
        {
            Telemetry.EnvironmentPayload environment = _lastFrame?.environment;
            if (environment == null)
            {
                return y;
            }

            string text = $"wind {environment.wind_speed_ms:0.0} m/s    rotor {environment.rotor_rpm:0.0} rpm    " +
                          $"power {environment.active_power_kw:0} kW    ambient {environment.ambient_temp_c:0.0} °C";
            GUI.Label(new Rect(16f + 14f, y, width - 28f, 20f), text, _body);
            return y + _rowHeight * 0.6f;
        }

        private float DrawComponents(float y, float width)
        {
            if (_rig == null)
            {
                return y;
            }

            foreach (Avatar.ComponentAvatar avatar in _rig.Avatars)
            {
                float health = avatar.Health;
                Color color = HealthPalette.ColorFor(health);

                GUI.Label(new Rect(30f, y, 110f, 20f), avatar.Label, _body);

                Rect bar = new Rect(146f, y + 3f, width - 200f, 14f);
                Color previous = GUI.color;
                GUI.color = new Color(0f, 0f, 0f, 0.55f);
                GUI.DrawTexture(bar, Texture2D.whiteTexture);
                GUI.color = color;
                GUI.DrawTexture(new Rect(bar.x, bar.y, bar.width * health, bar.height), Texture2D.whiteTexture);
                GUI.color = previous;

                Telemetry.ComponentPayload component = _lastFrame?.Component(avatar.ComponentId);
                string reason = component != null ? component.PrimaryReason() : string.Empty;
                GUI.Label(new Rect(bar.x, bar.y + 16f, bar.width, 18f), $"{health * 100f:0} %  {reason}", _caption);
                y += _rowHeight;
            }

            return y;
        }

        private void EnsureStyles()
        {
            if (_panel != null)
            {
                return;
            }

            _panel = new GUIStyle(GUI.skin.box);
            _title = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, fontSize = 14 };
            _body = new GUIStyle(GUI.skin.label) { fontSize = 12 };
            _caption = new GUIStyle(GUI.skin.label) { fontSize = 10 };
            _title.normal.textColor = Color.white;
            _body.normal.textColor = new Color(0.88f, 0.9f, 0.92f);
            _caption.normal.textColor = new Color(0.72f, 0.76f, 0.8f);
        }
    }
}