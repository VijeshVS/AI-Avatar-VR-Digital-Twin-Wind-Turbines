using NUnit.Framework;
using Vrar.Telemetry;

namespace Vrar.Tests
{
    /// <summary>
    /// The clock handover and the focus command, tested without a network: the
    /// follow flag changes the URL, and the follower consumes each sequence once.
    /// </summary>
    public class SessionFollowTests
    {
        [Test]
        public void FollowModeOmitsTheExplicitTimestamp()
        {
            string url = HttpTelemetrySource.TelemetryUrl("http://host:8000/", 120, true);

            Assert.That(url, Is.EqualTo("http://host:8000/api/telemetry"));
        }

        [Test]
        public void ExplicitModeKeepsTheTimestamp()
        {
            string url = HttpTelemetrySource.TelemetryUrl("http://host:8000", 120, false);

            Assert.That(url, Is.EqualTo("http://host:8000/api/telemetry?t=120.0"));
        }

        [Test]
        public void TurbineIdIsCarriedInTheQueryString()
        {
            string explicitUrl = HttpTelemetrySource.TelemetryUrl(
                "http://host:8000", 120, false, "T7");
            string followUrl = HttpTelemetrySource.TelemetryUrl(
                "http://host:8000", 120, true, "T7");

            Assert.That(explicitUrl, Is.EqualTo("http://host:8000/api/telemetry?t=120.0&turbine_id=T7"));
            Assert.That(followUrl, Is.EqualTo("http://host:8000/api/telemetry?turbine_id=T7"));
        }

        [Test]
        public void FocusCommandIsAppliedOncePerSequence()
        {
            var follower = new SessionFocusFollower();
            var session = new SessionPayload { focus = "gearbox", focus_seq = 1 };

            Assert.That(follower.TryConsume(session, out string first, out bool clear), Is.True);
            Assert.That(first, Is.EqualTo("gearbox"));
            Assert.That(clear, Is.False);

            Assert.That(follower.TryConsume(session, out _, out _), Is.False,
                "the same sequence must not re-grab the camera");

            session.focus = "generator";
            session.focus_seq = 2;

            Assert.That(follower.TryConsume(session, out string second, out _), Is.True);
            Assert.That(second, Is.EqualTo("generator"));
        }

        [Test]
        public void EmptyFocusClearsOnce()
        {
            var follower = new SessionFocusFollower();
            var session = new SessionPayload { focus = string.Empty, focus_seq = 3 };

            Assert.That(follower.TryConsume(session, out string component, out bool clear), Is.True);
            Assert.That(component, Is.Null);
            Assert.That(clear, Is.True);
            Assert.That(follower.TryConsume(session, out _, out _), Is.False);
        }

        [Test]
        public void InitialNullFocusIsConsumedOnce()
        {
            var follower = new SessionFocusFollower();
            var session = new SessionPayload { focus = null, focus_seq = 0 };

            Assert.That(follower.TryConsume(session, out _, out bool clear), Is.True);
            Assert.That(clear, Is.True);
            Assert.That(follower.TryConsume(session, out _, out _), Is.False);
        }

        [Test]
        public void ResetReappliesTheCurrentSequence()
        {
            var follower = new SessionFocusFollower();
            var session = new SessionPayload { focus = "gearbox", focus_seq = 4 };

            Assert.That(follower.TryConsume(session, out _, out _), Is.True);
            follower.Reset();
            Assert.That(follower.TryConsume(session, out string component, out _), Is.True);
            Assert.That(component, Is.EqualTo("gearbox"));
        }
    }
}
