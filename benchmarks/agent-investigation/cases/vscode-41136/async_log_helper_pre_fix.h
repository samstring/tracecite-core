Source: pre-fix gabime/spdlog async_log_helper.h, reduced to the relevant lifecycle and waiting logic.

inline spdlog::details::async_log_helper::~async_log_helper()
{
    try
    {
        push_msg(async_msg(async_msg_type::terminate));
        _worker_thread.join();
    }
    catch (...)
    {
    }
}

inline bool spdlog::details::async_log_helper::process_next_msg(
    log_clock::time_point& last_pop,
    log_clock::time_point& last_flush)
{
    async_msg incoming_async_msg;

    if (_q.dequeue(incoming_async_msg))
    {
        last_pop = details::os::now();
        switch (incoming_async_msg.msg_type)
        {
        case async_msg_type::flush:
            _flush_requested = true;
            break;
        case async_msg_type::terminate:
            _flush_requested = true;
            _terminate_requested = true;
            break;
        default:
            break;
        }
        return true;
    }
    else
    {
        auto now = details::os::now();
        handle_flush_interval(now, last_flush);
        sleep_or_yield(now, last_pop);
        return !_terminate_requested;
    }
}

inline void spdlog::details::async_log_helper::sleep_or_yield(
    const spdlog::log_clock::time_point& now,
    const log_clock::time_point& last_op_time)
{
    using namespace std::this_thread;
    using std::chrono::milliseconds;
    using std::chrono::microseconds;

    auto time_since_op = now - last_op_time;

    if (time_since_op <= microseconds(50))
        return;

    if (time_since_op <= microseconds(100))
        return std::this_thread::yield();

    if (time_since_op <= milliseconds(200))
        return sleep_for(milliseconds(20));

    return sleep_for(milliseconds(500));
}
