using System;
using System.Collections;
using System.IO;
using System.Text;
using UnityEngine;
using Vrar.AI;
using Vrar.Avatar;
using Vrar.Presentation;
using Vrar.Telemetry;
using Vrar.Turbine;

namespace Vrar.Bootstrap
{
    /// <summary>
    /// Wires the whole PoC together: build the turbine, poll the telemetry
    /// service, push frames into the rig, drive the HUD and the audio.
    ///
    /// Endpoint resolution order: <c>-vrar-endpoint &lt;url&gt;</c> command-line
    /// argument, then the <c>VRAR_TELEMETRY_ENDPOINT</c> environment variable,
    /// then <c>http://127.0.0.1:8000</c>. Pass <c>-vrar-sample</c> to replay the
    /// bundled frames instead, which needs no service at all.
    /// </summary>
    public sealed class MvpBootstrap : MonoBehaviour
    {
        private const string SampleArgument = "-vrar-sample";
        private const string EndpointArgument = "-vrar-endpoint";
        private const string TimeArgument = "-vrar-time";
        private const string FollowArgument = "-vrar-follow";
        private const string TurbineArgument = "-vrar-turbine";
        private const string FollowEnvironment = "VRAR_FOLLOW";
        private const string TurbineEnvironment = "VRAR_TURBINE_ID";
        private const string DefaultEndpoint = "http://127.0.0.1:8000";
        private const string DefaultTurbineId = "T1";
        private const string SamplePath = "telemetry_sample.json";

        [SerializeField, Min(0.1f)] private float _pollIntervalSeconds = 1f;
        [SerializeField] private bool _buildRigIfMissing = true;
        [SerializeField] private bool _enableAudio = true;
        [SerializeField] private TurbineRig _rig;

        private ITelemetrySource _source;
        private ProceduralAudio _audio;
        private HudOverlay _hud;
        private ComponentFocusFlight _focusFlight;
        private ComponentFocusIsolation _focusIsolation;
        private float _pollTimer;
        private int _requestToken;
        private bool _connected;
        private bool _playing = true;
        private bool _followServerClock;
        private readonly SessionFocusFollower _focusFollower = new SessionFocusFollower();
        private string _endpoint = DefaultEndpoint;
        private string _turbineId = DefaultTurbineId;
        private string _statusOverride = string.Empty;

        public TurbineRig Rig => _rig;
        public bool Connected => _connected;
        public string Endpoint => _endpoint;
        public string TurbineId => _turbineId;
        public bool FollowingServerClock => _followServerClock;
        public TelemetryFrame LastFrame => _rig?.LastFrame;
        public ComponentFocus Focus => _hud?.Focus;

        private void Awake()
        {
            _endpoint = ResolveEndpoint();
            _turbineId = ResolveTurbineId();
            _followServerClock = ResolveFollowServerClock();
            if (_rig == null)
            {
                _rig = FindFirstObjectByType<TurbineRig>();
            }

            if (_rig == null && _buildRigIfMissing)
            {
                TurbineFactory.BuildGround();
                _rig = TurbineFactory.Build();
            }

            _hud = gameObject.AddComponent<HudOverlay>();
            _hud.SetRig(_rig);

            _focusFlight = gameObject.AddComponent<ComponentFocusFlight>();
            _focusFlight.Bind(_rig, _hud.Focus);

            _focusIsolation = gameObject.AddComponent<ComponentFocusIsolation>();
            _focusIsolation.Bind(_rig, _hud.Focus);

            CopilotPanel copilot = gameObject.AddComponent<CopilotPanel>();
            copilot.Bind(this);

            _source = CreateSource();
            if (_source is HttpTelemetrySource http)
            {
                _endpoint = http.Endpoint;
            }
        }

        private void Start()
        {
            if (_enableAudio && !Application.isBatchMode)
            {
                _audio = gameObject.AddComponent<ProceduralAudio>();
                foreach (ComponentAvatar avatar in _rig.Avatars)
                {
                    avatar.AttachAlarm(_audio.AlarmSource);
                }
            }
        }

        private ITelemetrySource CreateSource()
        {
            float? startTime = ParseFloatArgument(TimeArgument);
            if (startTime.HasValue)
            {
                // Scrub straight to a point in the scenario: handy for demoing a
                // degraded machine without waiting out the fault ramp.
                _requestToken = Mathf.Max(0, Mathf.RoundToInt(startTime.Value));
            }

            if (HasArgument(SampleArgument))
            {
                TelemetryFrame[] frames = SampleFrames.LoadFromStreamingAssets(SamplePath);
                if (frames != null && frames.Length > 0)
                {
                    return new ReplayTelemetrySource(frames);
                }

                Debug.LogWarning("[VRAR] -vrar-sample given but no sample frames were found; falling back to HTTP.");
            }

            return new HttpTelemetrySource(
                _endpoint, followServerClock: _followServerClock, turbineId: _turbineId);
        }

        private static float? ParseFloatArgument(string name)
        {
            string[] arguments = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name && float.TryParse(arguments[i + 1], out float value))
                {
                    return value;
                }
            }

            return null;
        }

        private void Update()
        {
            if (!_playing || _rig == null)
            {
                return;
            }

            _pollTimer -= Time.deltaTime;
            if (_pollTimer > 0f)
            {
                return;
            }

            _pollTimer = _pollIntervalSeconds;
            _requestToken++;
            StartCoroutine(Poll());
        }

        private IEnumerator Poll()
        {
            bool handled = false;
            yield return _source.Fetch(_requestToken, (frame, error) =>
            {
                handled = true;
                if (frame != null)
                {
                    _connected = true;
                    _rig.Apply(frame);
                }
                else
                {
                    _connected = false;
                    _statusOverride = error;
                }
            });

            if (!handled)
            {
                _connected = false;
            }

            UpdateAudio();

            if (_followServerClock)
            {
                yield return PollSession();
            }
        }

        private void LateUpdate()
        {
            if (_hud == null)
            {
                return;
            }

            string status = _connected
                ? $"{_endpoint}"
                : (_statusOverride.Length > 0 ? _statusOverride : "no response");
            if (_followServerClock)
            {
                status = $"{status}  ·  web control";
            }

            _hud.SetFrame(_rig?.LastFrame, _connected, status);
        }

        private void UpdateAudio()
        {
            if (_audio == null)
            {
                return;
            }

            TelemetryFrame frame = _rig?.LastFrame;
            _audio.UpdateHum(frame?.environment?.rotor_rpm ?? 0f, frame?.Signal("pitch_angle_deg") ?? 0f, _connected);
        }

        /// <summary>
        /// Read the shared session and apply a new focus command exactly once.
        /// Polled only in follow mode, so the desktop path pays no extra request.
        /// </summary>
        private IEnumerator PollSession()
        {
            using UnityEngine.Networking.UnityWebRequest request =
                UnityEngine.Networking.UnityWebRequest.Get($"{_endpoint}/api/session");
            request.timeout = 3;
            yield return request.SendWebRequest();

            if (request.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
            {
                yield break;
            }

            SessionPayload session;
            try
            {
                session = JsonUtility.FromJson<SessionPayload>(request.downloadHandler.text);
            }
            catch (Exception)
            {
                yield break;
            }

            if (!_focusFollower.TryConsume(session, out string componentId, out bool clearFocus))
            {
                yield break;
            }

            if (clearFocus)
            {
                Focus?.Clear();
                yield break;
            }

            int index = CopilotPanel.IndexOfComponent(_rig, componentId);
            if (index >= 0)
            {
                Focus?.Select(index);
            }
        }

        /// <summary>Switch scenario through the service and reset the playback clock.</summary>
        public void SelectScenario(string scenarioId)
        {
            if (_source is HttpTelemetrySource)
            {
                StartCoroutine(PostScenario(scenarioId));
            }
            else
            {
                _source.CancelAll();
            }

            _requestToken = 0;
            _pollTimer = 0f;
        }

        private IEnumerator PostScenario(string scenarioId)
        {
            using UnityEngine.Networking.UnityWebRequest request =
                new UnityEngine.Networking.UnityWebRequest($"{_endpoint}/api/scenario/{scenarioId}", "POST");
            request.downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer();
            yield return request.SendWebRequest();
        }

        /// <summary>Scrub the playback clock, locally or on the shared session.</summary>
        public void SetPlaybackTime(float seconds)
        {
            if (_followServerClock)
            {
                StartCoroutine(PostSessionTime(seconds));
                return;
            }

            _requestToken = Mathf.Max(0, Mathf.RoundToInt(seconds));
            _pollTimer = 0f;
        }

        public void SetPlaying(bool playing)
        {
            _playing = playing;
            if (_followServerClock)
            {
                StartCoroutine(PostSessionPlaying(playing));
            }

            if (!playing && _audio != null)
            {
                _audio.StopAlarm();
            }
        }

        private IEnumerator PostSessionTime(float seconds)
        {
            yield return PostSession(
                $"{{\"t\":{seconds.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)}}}");
        }

        private IEnumerator PostSessionPlaying(bool playing)
        {
            yield return PostSession($"{{\"playing\":{(playing ? "true" : "false")}}}");
        }

        private IEnumerator PostSession(string json)
        {
            using UnityEngine.Networking.UnityWebRequest request =
                new UnityEngine.Networking.UnityWebRequest($"{_endpoint}/api/session", "POST");
            request.uploadHandler =
                new UnityEngine.Networking.UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            request.downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = 3;
            yield return request.SendWebRequest();
        }

        private static bool ResolveFollowServerClock()
        {
            // An explicit time or an offline replay owns the clock; never fight it.
            if (HasArgument(SampleArgument) || HasArgument(TimeArgument))
            {
                return false;
            }

            string fromEnvironment = System.Environment.GetEnvironmentVariable(FollowEnvironment);
            return HasArgument(FollowArgument)
                || string.Equals(fromEnvironment, "1", StringComparison.OrdinalIgnoreCase)
                || string.Equals(fromEnvironment, "true", StringComparison.OrdinalIgnoreCase);
        }

        private static string ResolveTurbineId()
        {
            string[] arguments = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == TurbineArgument && !string.IsNullOrWhiteSpace(arguments[i + 1]))
                {
                    return arguments[i + 1].Trim();
                }
            }

            string fromEnvironment = System.Environment.GetEnvironmentVariable(TurbineEnvironment);
            return string.IsNullOrWhiteSpace(fromEnvironment)
                ? DefaultTurbineId
                : fromEnvironment.Trim();
        }

        private static string ResolveEndpoint()
        {
            string[] arguments = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == EndpointArgument)
                {
                    return arguments[i + 1].TrimEnd('/');
                }
            }

            string fromEnvironment = System.Environment.GetEnvironmentVariable("VRAR_TELEMETRY_ENDPOINT");
            return string.IsNullOrWhiteSpace(fromEnvironment) ? DefaultEndpoint : fromEnvironment.TrimEnd('/');
        }

        private static bool HasArgument(string name)
        {
            foreach (string argument in System.Environment.GetCommandLineArgs())
            {
                if (argument == name)
                {
                    return true;
                }
            }

            return false;
        }
    }
}