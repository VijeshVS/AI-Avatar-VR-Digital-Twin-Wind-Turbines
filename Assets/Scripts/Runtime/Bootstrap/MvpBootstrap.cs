using System.Collections;
using System.IO;
using UnityEngine;
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
        private const string DefaultEndpoint = "http://127.0.0.1:8000";
        private const string SamplePath = "telemetry_sample.json";

        [SerializeField, Min(0.1f)] private float _pollIntervalSeconds = 1f;
        [SerializeField] private bool _buildRigIfMissing = true;
        [SerializeField] private bool _enableAudio = true;

        private TurbineRig _rig;
        private ITelemetrySource _source;
        private ProceduralAudio _audio;
        private HudOverlay _hud;
        private float _pollTimer;
        private int _requestToken;
        private bool _connected;
        private bool _playing = true;
        private string _endpoint = DefaultEndpoint;
        private string _statusOverride = string.Empty;

        public TurbineRig Rig => _rig;
        public bool Connected => _connected;
        public string Endpoint => _endpoint;
        public TelemetryFrame LastFrame => _rig?.LastFrame;

        private void Awake()
        {
            _endpoint = ResolveEndpoint();
            _rig = FindFirstObjectByType<TurbineRig>();
            if (_rig == null && _buildRigIfMissing)
            {
                TurbineFactory.BuildGround();
                _rig = TurbineFactory.Build();
            }

            _hud = gameObject.AddComponent<HudOverlay>();
            _hud.SetRig(_rig);

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
                _requestToken = Mathf.Max(0, Mathf.RoundToInt(startTime.Value * 10f));
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

            return new HttpTelemetrySource(_endpoint);
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

        /// <summary>Scrub the playback clock, for scrubbing through a scenario by hand.</summary>
        public void SetPlaybackTime(float seconds)
        {
            _requestToken = Mathf.Max(0, Mathf.RoundToInt(seconds * 10f));
            _pollTimer = 0f;
        }

        public void SetPlaying(bool playing)
        {
            _playing = playing;
            if (!playing && _audio != null)
            {
                _audio.StopAlarm();
            }
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